"""Tiendas: listado del snapshot y prender/pausar vía CLI (dry-run por defecto)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, HTTPException, Request

from ..deps import audit, get_settings, operator
from .cli_helpers import require_platform, require_session, run_tolerant, store_args, write_flags

router = APIRouter(prefix="/api/stores")

UBER_DURATIONS = ("10", "20", "30", "60", "rest_of_day")
UBER_REASONS = ("CLOSING_EARLY", "PROBLEM_IN_RESTAURANT", "OUT_OF_ITEM", "OTHER")
PYA_REASONS = (
    "TOO_BUSY_KITCHEN", "TOO_BUSY_NO_DRIVERS", "UPDATES_IN_MENU", "TECHNICAL_PROBLEM",
    "BAD_WEATHER", "OTHER", "CLOSED",
)
WRITE_TIMEOUT = 300


def _snapshot_stores() -> list[dict]:
    try:
        snap = json.loads(get_settings().snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [s for s in snap.get("stores") or [] if isinstance(s, dict)]


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in (
        "platform", "store_id", "name", "brand", "status", "open_now", "enabled",
        "reason", "since", "until", "next_open", "next_close", "slot", "excluded",
    )}


@router.get("")
async def list_stores(request: Request, platform: str | None = None, brand: str | None = None,
                      status: str | None = None, open_now: bool | None = None,
                      excluded: bool | None = None, q: str | None = None):
    operator(request)
    rows = [_public(s) for s in _snapshot_stores()]
    if platform and platform != "todas":
        rows = [r for r in rows if r.get("platform") == platform]
    if brand and brand != "todas":
        rows = [r for r in rows if r.get("brand") == brand]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if open_now is not None:
        rows = [r for r in rows if bool(r.get("open_now")) is open_now]
    if excluded is not None:
        rows = [r for r in rows if bool(r.get("excluded")) is excluded]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in (r.get("name") or "").lower()]
    available = get_settings().snapshot_path.is_file()
    return {
        "stores": rows,
        "count": len(rows),
        "snapshot_available": available,
        "note": None if available else "Sin snapshot: use Monitoreo → Actualizar snapshot para poblar las tiendas.",
    }


@router.get("/meta/options")
async def store_options(request: Request):
    operator(request)
    return {
        "uber": {"durations": list(UBER_DURATIONS), "reasons": list(UBER_REASONS)},
        "pedidosya": {"reasons": list(PYA_REASONS)},
    }


@router.get("/{platform}/{store_id}")
async def store_detail(request: Request, platform: str, store_id: str):
    operator(request)
    require_platform(platform)
    for s in _snapshot_stores():
        if s.get("platform") == platform and str(s.get("store_id")) == store_id:
            return {"store": _public(s)}
    raise HTTPException(status_code=404, detail="Tienda no encontrada en el snapshot")


def _write(user: str, action: str, body: dict, extra: list[str]) -> dict:
    settings = get_settings()
    platform = require_platform(str(body.get("platform") or ""))
    confirm = body.get("confirm") is True
    args = [action, *store_args(body), *write_flags(confirm), *extra]
    require_session(settings, platform)
    try:
        result = run_tolerant(settings, platform, args, WRITE_TIMEOUT, confirm=confirm)
    except HTTPException as exc:
        audit(user, f"stores.{action}", platform, not confirm, "error", str(exc.detail))
        raise
    audit(user, f"stores.{action}", platform, not confirm, "ok" if confirm else "dry-run", " ".join(extra))
    result["platform"] = platform
    result["action"] = action
    if confirm:
        result["note"] = "Enviado a la plataforma. Actualice el snapshot para verificar el estado resultante."
    return result


@router.post("/activate")
async def activate_stores(request: Request, body: dict = Body(...)):
    user = operator(request)
    return await asyncio.to_thread(_write, user, "activate", body or {}, [])


@router.post("/pause")
async def pause_stores(request: Request, body: dict = Body(...)):
    user = operator(request)
    body = body or {}
    platform = require_platform(str(body.get("platform") or ""))
    extra: list[str] = []
    if platform == "uber":
        duration = str(body.get("duration") or "rest_of_day")
        if duration not in UBER_DURATIONS:
            raise HTTPException(status_code=400, detail="Duración inválida para Uber (10, 20, 30, 60 o rest_of_day)")
        reason = str(body.get("reason") or "OTHER")
        if reason not in UBER_REASONS:
            raise HTTPException(status_code=400, detail="Motivo inválido para Uber")
        extra += ["--duration", duration, "--reason", reason]
        if body.get("comment"):
            extra += ["--comment", str(body["comment"])[:300]]
    else:
        reason = str(body.get("reason") or "TOO_BUSY_KITCHEN")
        if reason not in PYA_REASONS:
            raise HTTPException(status_code=400, detail="Motivo inválido para PedidosYa")
        extra += ["--reason", reason]
        minutes = body.get("minutes")
        if minutes not in (None, ""):
            try:
                m = int(minutes)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="minutes debe ser un entero") from exc
            if not 1 <= m <= 1440:
                raise HTTPException(status_code=400, detail="minutes fuera de rango (1-1440)")
            extra += ["--minutes", str(m)]
    return await asyncio.to_thread(_write, user, "pause", body, extra)
