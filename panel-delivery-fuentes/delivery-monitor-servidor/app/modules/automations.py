"""Automatizaciones: jobs con cron (America/Santiago) que refrescan el snapshot o generan reportes."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, Request

from delivery_monitor.parseutil import iso_chile
from delivery_monitor.sanitize import sanitize

from ..deps import audit, get_settings, operator

log = logging.getLogger("delivery_monitor.automations")
router = APIRouter(prefix="/api/automations")

TZ = ZoneInfo("America/Santiago")
READ_KINDS = ("refresh_snapshot", "report")
WRITE_KINDS = ("catalog_activate_menu", "catalog_soldout", "stores_pause", "stores_activate")
MIN_GAP_SECONDS = 15 * 60
_lock = threading.Lock()
_running: set[str] = set()
_last_started: dict[str, float] = {}


def _path():
    return get_settings().data_dir / "automations.json"


def _read() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def _allow_scheduled_writes() -> bool:
    return (os.environ.get("ALLOW_SCHEDULED_WRITES") or "").strip().lower() in {"1", "true", "yes"}


# ---------- cron de 5 campos ----------

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("paso inválido")
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < lo or end > hi or start > end:
            raise ValueError("fuera de rango")
        out.update(range(start, end + 1, step))
    return out


def parse_cron(expr: str) -> tuple[set[int], ...]:
    parts = (expr or "").split()
    if len(parts) != 5:
        raise ValueError("El cron debe tener 5 campos: minuto hora día mes día-semana")
    fields = []
    for i, (spec, (lo, hi)) in enumerate(zip(parts, _RANGES)):
        if i == 4:
            spec = spec.replace("7", "0")
        fields.append(_field(spec, lo, hi))
    return tuple(fields)


def cron_matches(expr: str, when: dt.datetime) -> bool:
    minute, hour, dom, month, dow = parse_cron(expr)
    cron_dow = (when.weekday() + 1) % 7
    return when.minute in minute and when.hour in hour and when.month in month and when.day in dom and cron_dow in dow


def _validate(kind: str, schedule: str, payload: dict) -> None:
    if kind in WRITE_KINDS:
        if not _allow_scheduled_writes():
            raise HTTPException(status_code=403, detail="Escrituras programadas deshabilitadas (ALLOW_SCHEDULED_WRITES=false)")
        raise HTTPException(status_code=501, detail="Escrituras programadas aún no cableadas: use el módulo manual con dry-run")
    if kind not in READ_KINDS:
        raise HTTPException(status_code=400, detail="kind debe ser refresh_snapshot o report")
    if schedule:
        try:
            parse_cron(schedule)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Cron inválido: {exc}") from exc
    if kind == "report" and not str(payload.get("report") or ""):
        raise HTTPException(status_code=400, detail="Una automatización de reporte necesita payload.report")


def _public(entry: dict) -> dict:
    return {k: entry.get(k) for k in (
        "id", "name", "kind", "schedule", "payload", "enabled", "created_by",
        "created_at", "last_run_at", "last_status", "last_error",
    )} | {"running": entry.get("id") in _running}


def _record(auto_id: str, status: str, error: str | None) -> None:
    with _lock:
        data = _read()
        if auto_id in data:
            data[auto_id]["last_run_at"] = iso_chile()
            data[auto_id]["last_status"] = status
            data[auto_id]["last_error"] = error
            _write(data)


def execute(entry: dict, actor: str) -> dict:
    """Corre una automatización de lectura. Usa el mismo candado que el refresh manual."""
    auto_id, kind, payload = entry["id"], entry.get("kind"), entry.get("payload") or {}
    with _lock:
        if auto_id in _running:
            raise HTTPException(status_code=409, detail="Esta automatización ya está corriendo")
        _running.add(auto_id)
        _last_started[auto_id] = time.monotonic()
    audit(actor, "automations.run", auto_id, False, "inicio", str(kind))
    try:
        if kind == "refresh_snapshot":
            from ..main import _locked_refresh

            snap = _locked_refresh()
            summary = "snapshot actualizado" if snap.get("available") else (snap.get("message") or "snapshot sin datos")
            status = "ok" if snap.get("available") else "warn"
        elif kind == "report":
            from .reports import _run_report

            job = _run_report(str(payload.get("report") or ""), payload, actor)
            summary = f"{job.get('result_summary') or 'reporte generado'} (job {job.get('id')})"
            status = "ok" if job.get("status") == "done" else "warn"
        else:
            raise HTTPException(status_code=501, detail=f"kind={kind} no se ejecuta en v1")
    except HTTPException as exc:
        _record(auto_id, "error", sanitize(str(exc.detail)))
        audit(actor, "automations.run", auto_id, False, "error", str(exc.detail))
        raise
    except Exception as exc:
        err = sanitize(str(exc))
        _record(auto_id, "error", err)
        audit(actor, "automations.run", auto_id, False, "error", err)
        raise HTTPException(status_code=502, detail=err) from exc
    finally:
        with _lock:
            _running.discard(auto_id)
    _record(auto_id, status, None if status == "ok" else summary)
    audit(actor, "automations.run", auto_id, False, status, summary)
    return {"ok": status == "ok", "kind": kind, "status": status, "summary": summary}


def due(now: dt.datetime | None = None) -> list[dict]:
    now = (now or dt.datetime.now(TZ)).astimezone(TZ).replace(second=0, microsecond=0)
    mono = time.monotonic()
    out = []
    with _lock:
        entries = list(_read().values())
    for entry in entries:
        if not entry.get("enabled") or not entry.get("schedule") or entry.get("kind") not in READ_KINDS:
            continue
        if entry["id"] in _running or mono - _last_started.get(entry["id"], -1e12) < MIN_GAP_SECONDS:
            continue
        try:
            if cron_matches(entry["schedule"], now):
                out.append(entry)
        except ValueError:
            continue
    return out


async def scheduler_loop(stop: asyncio.Event) -> None:
    log.info("programador de automatizaciones activo (cron en America/Santiago)")
    while not stop.is_set():
        wait = 60 - dt.datetime.now(TZ).second + 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
            return
        except asyncio.TimeoutError:
            pass
        for entry in due():
            try:
                await asyncio.to_thread(execute, entry, f"automation:{entry['id']}")
            except Exception as exc:
                log.warning("automatización %s falló: %s", entry.get("id"), sanitize(str(getattr(exc, "detail", exc))))


# ---------- rutas ----------

@router.get("")
async def list_automations(request: Request):
    operator(request)
    with _lock:
        items = [_public(v) for v in _read().values()]
    return {
        "automations": sorted(items, key=lambda x: x.get("created_at") or ""),
        "kinds": list(READ_KINDS),
        "scheduled_writes_allowed": _allow_scheduled_writes(),
        "timezone": "America/Santiago",
        "min_gap_minutes": MIN_GAP_SECONDS // 60,
    }


@router.post("")
async def create_automation(request: Request, body: dict = Body(...)):
    user = operator(request)
    body = body or {}
    kind = str(body.get("kind") or "")
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="Falta el nombre")
    schedule = str(body.get("schedule") or "").strip()
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    _validate(kind, schedule, payload)
    entry = {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "kind": kind,
        "schedule": schedule,
        "payload": payload,
        "enabled": body.get("enabled") is not False,
        "created_by": user,
        "created_at": iso_chile(),
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
    }
    with _lock:
        data = _read()
        data[entry["id"]] = entry
        _write(data)
    audit(user, "automations.create", entry["id"], False, "ok", kind)
    return _public(entry)


@router.patch("/{auto_id}")
async def patch_automation(request: Request, auto_id: str, body: dict = Body(...)):
    user = operator(request)
    body = body or {}
    with _lock:
        data = _read()
        entry = data.get(auto_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Automatización no encontrada")
        schedule = str(body.get("schedule", entry.get("schedule")) or "").strip()
        payload = body["payload"] if isinstance(body.get("payload"), dict) else entry.get("payload") or {}
        _validate(entry.get("kind") or "", schedule, payload)
        entry.update({"schedule": schedule, "payload": payload})
        if "name" in body:
            entry["name"] = str(body["name"]).strip()[:120] or entry["name"]
        if "enabled" in body:
            entry["enabled"] = body["enabled"] is True
        data[auto_id] = entry
        _write(data)
    audit(user, "automations.patch", auto_id, False, "ok")
    return _public(entry)


@router.delete("/{auto_id}")
async def delete_automation(request: Request, auto_id: str):
    user = operator(request)
    with _lock:
        data = _read()
        if auto_id not in data:
            raise HTTPException(status_code=404, detail="Automatización no encontrada")
        del data[auto_id]
        _write(data)
    audit(user, "automations.delete", auto_id, False, "ok")
    return {"deleted": True, "id": auto_id}


@router.post("/{auto_id}/run")
async def run_automation(request: Request, auto_id: str):
    user = operator(request)
    with _lock:
        entry = _read().get(auto_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Automatización no encontrada")
    return await asyncio.to_thread(execute, entry, user)
