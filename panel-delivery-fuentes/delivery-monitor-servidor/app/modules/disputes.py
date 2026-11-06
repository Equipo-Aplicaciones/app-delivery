"""Disputas + imágenes: cobros Uber, reclamos PedidosYa y fotos de la app delivery por pedido.

- Uber: `disputes --json`, `dispute-photos` y `dispute` (dry-run por defecto).
- PedidosYa: `issues` son reclamos, no disputas; `order <id> --photos`; no hay envío por API.
- App delivery: fotos de la tienda desde la Edge Function `evidencia`, por proxy autenticado.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, Response

from delivery_monitor.adapters.pya import NO_DIRECT_LIST, normalize_issue_tile
from delivery_monitor.adapters.runner import CliError, run_cli, run_json_cli
from delivery_monitor.adapters.uber import default_window, normalize_dispute, parse_counters
from delivery_monitor.parseutil import format_clp, iso_chile, parse_clp, parse_requested
from delivery_monitor.sanitize import looks_like_auth_failure, sanitize

from ..config import Settings
from ..deps import audit, get_settings, operator
from . import evidence, media
from .credentials import has_session

router = APIRouter()

UBER_STATUSES = ("pending", "charged", "disputed", "accepted", "rejected")
UBER_REASONS = (
    "CUSTOMER_MISTAKE", "CUSTOMER_PROVIDED_EVIDENCE_INCORRECT", "DELIVERY_DRIVER_RELATED",
    "EVIDENCE_UNCONVINCING", "INCORRECT_REFUND_AMOUNT", "OTHER", "STORE_EVIDENCE_AVAILABLE",
)
EVIDENCE_EXT = {".jpg", ".jpeg", ".png", ".mp4", ".mpg", ".3gpp", ".pdf"}
MAX_EVIDENCE = 3
MAX_EVIDENCE_BYTES = 100 * 1024 * 1024
LIST_TIMEOUT = int(os.environ.get("UBER_DISPUTES_TIMEOUT", "360"))
DETAIL_TIMEOUT = int(os.environ.get("DISPUTE_DETAIL_TIMEOUT", "300"))
SUBMIT_TIMEOUT = int(os.environ.get("DISPUTE_SUBMIT_TIMEOUT", "180"))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STORE_ID_RE = re.compile(r"^[A-Za-z0-9;_-]{1,80}$")
UNVERIFIED = (
    "Envío real a Uber no verificado en vivo: SubmitDispute con --yes nunca se probó en producción "
    "y la evidencia multipart no está validada. Revise en el portal de Uber si la disputa quedó registrada."
)
PYA_SUBMIT_501 = (
    "PedidosYa no tiene endpoint de envío de disputas por API: el portal abre el Help Center "
    "(cases-api). Este panel no simula el envío."
)

_cli_slots = threading.BoundedSemaphore(2)
_index_lock = threading.Lock()


def _allow_real_submit() -> bool:
    return (os.environ.get("ALLOW_UBER_DISPUTE_SUBMIT") or "").strip().lower() in {"1", "true", "yes"}


def _check_date(value: str | None, name: str) -> str | None:
    if value in (None, ""):
        return None
    if not DATE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{name} debe ser AAAA-MM-DD")
    return value


def _check_store(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not STORE_ID_RE.match(value):
        raise HTTPException(status_code=400, detail="store_id inválido")
    return value


def _order(order_id: str) -> str:
    try:
        return media.valid_order(order_id)
    except media.MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run_json(script: str, args: list[str], cwd: str, timeout: int):
    with _cli_slots:
        return run_json_cli(script, args, cwd, timeout)


def _source_error(exc: CliError) -> dict:
    return {"status": "error", "auth": bool(exc.auth), "error": sanitize(str(exc))}


def _missing(platform: str) -> dict:
    label = "Uber" if platform == "uber" else "PedidosYa"
    return {"status": "missing_credentials", "auth": True,
            "error": f"Sin sesión de {label}: cárguela en Credenciales. No se consultó la plataforma."}


def _raw_snapshot(settings: Settings) -> dict:
    try:
        data = json.loads(settings.snapshot_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _uber_store_ids(settings: Settings) -> dict[str, str]:
    return {
        str(s.get("name")): str(s.get("store_id"))
        for s in _raw_snapshot(settings).get("stores") or []
        if isinstance(s, dict) and s.get("platform") == "uber" and s.get("store_id")
    }


def _index_path(settings: Settings) -> Path:
    return settings.data_dir / "uber_pedidos.json"


def _read_index(settings: Settings) -> dict:
    try:
        data = json.loads(_index_path(settings).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _remember_uber(settings: Settings, rows: list[dict]) -> None:
    """Guarda workflow/tienda por pedido (ids internos, sin secretos) para armar la disputa."""
    stores = _uber_store_ids(settings)
    with _index_lock:
        index = _read_index(settings)
        for row in rows:
            oid = str(row.get("order_id") or "")
            if not oid:
                continue
            prev = index.get(oid, {})
            index[oid] = {
                "workflow_uuid": row.get("workflow_uuid") or prev.get("workflow_uuid"),
                "store_name": row.get("store_name") or prev.get("store_name"),
                "restaurant_uuid": stores.get(str(row.get("store_name"))) or prev.get("restaurant_uuid"),
                "seen_at": iso_chile(),
            }
        path = _index_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def _uber_ref(settings: Settings, order_id: str) -> dict:
    ref = dict(_read_index(settings).get(order_id) or {})
    if not ref.get("workflow_uuid"):
        for d in _raw_snapshot(settings).get("disputes") or []:
            if isinstance(d, dict) and d.get("platform") == "uber" and str(d.get("order_id")) == order_id:
                ref.update({"workflow_uuid": d.get("workflow_uuid"), "store_name": d.get("store_name")})
                break
    if ref.get("store_name") and not ref.get("restaurant_uuid"):
        ref["restaurant_uuid"] = _uber_store_ids(settings).get(str(ref["store_name"]))
    return ref


def _public_dispute(row: dict) -> dict:
    out = {k: row.get(k) for k in (
        "platform", "store_name", "brand", "order_id", "ordered_at", "amount_clp", "amount_display",
        "issue", "tag", "state", "eligibility", "window_start", "window_end",
    )}
    out["can_prepare"] = bool(row.get("workflow_uuid"))
    return out


def _media_view(settings: Settings, platform: str, order_id: str) -> list[dict]:
    base = "/api/disputes/uber" if platform == "uber" else "/api/orders/pedidosya"
    return [
        {**item, "url": f"{base}/{order_id}/media/{item['id']}"}
        for item in media.list_items(settings.media_dir, platform, order_id)
    ]


# ---------- listados ----------

def _uber_list_live(settings: Settings, status: str, start: str | None, end: str | None,
                    store_id: str | None, limit: int) -> dict:
    d_start, d_end = default_window()
    start, end = start or d_start, end or d_end
    window = {"start": start, "end": end, "label": f"{start} a {end} (America/Santiago)"}
    base = {"platform": "uber", "source": "live", "fetched_at": iso_chile(), "window": window,
            "filter_status": status, "disputes": None, "counters": None}
    if not has_session(settings, "uber"):
        return {**base, **_missing("uber")}
    args = ["disputes", "--json", "--status", status, "--start", start, "--end", end, "--max", str(limit)]
    if store_id:
        args += ["--id", store_id]
    try:
        out = _run_json(settings.uber_cli, args, settings.uber_cli_cwd, LIST_TIMEOUT)
    except CliError as exc:
        return {**base, **_source_error(exc)}
    if not isinstance(out.data, list):
        return {**base, "status": "error", "auth": False, "error": "uber.py disputes no devolvió una lista"}
    rows = [normalize_dispute(r, window) for r in out.data if isinstance(r, dict)]
    _remember_uber(settings, rows)
    counters, _, _ = parse_counters(out.stderr)
    return {**base, "status": "ok", "error": None, "auth": False, "counters": counters,
            "truncated": len(rows) >= limit, "disputes": [_public_dispute(r) for r in rows]}


def _uber_list_snapshot(settings: Settings) -> dict:
    snap = _raw_snapshot(settings)
    src = (snap.get("sources") or {}).get("uber") or {}
    if not snap:
        return {"platform": "uber", "source": "snapshot", "status": "pending", "disputes": None,
                "error": "Aún no hay snapshot. Use «Consultar Uber ahora» o un refresh.", "window": None,
                "fetched_at": None, "counters": None}
    rows = [d for d in snap.get("disputes") or [] if isinstance(d, dict) and d.get("platform") == "uber"]
    ok = src.get("disputes_status") == "ok"
    return {
        "platform": "uber", "source": "snapshot", "fetched_at": src.get("fetched_at"),
        "status": "ok" if ok else (src.get("disputes_status") or "pending"),
        "error": None if ok else sanitize(src.get("disputes_error") or src.get("error")),
        "window": src.get("disputes_window"), "counters": None,
        "disputes": [_public_dispute(r) for r in rows] if ok else None,
    }


def _pya_list(settings: Settings, live: bool, start: str | None, end: str | None, by_store: bool) -> dict:
    base = {"platform": "pedidosya", "disputes_status": "no_direct_list", "disputes": None,
            "note": NO_DIRECT_LIST, "fetched_at": None}
    if not live:
        snap = _raw_snapshot(settings)
        src = (snap.get("sources") or {}).get("pedidosya") or {}
        tiles = snap.get("complaint_tiles")
        status = "ok" if isinstance(tiles, list) and snap else "pending"
        return {**base, "source": "snapshot", "fetched_at": src.get("fetched_at"), "status": status,
                "error": None if status == "ok" else "Aún no hay snapshot con reclamos de PedidosYa.",
                "complaint_tiles": tiles if status == "ok" else None}
    if not has_session(settings, "pedidosya"):
        return {**base, "source": "live", "complaint_tiles": None, **_missing("pedidosya")}
    d_start, d_end = default_window()
    start, end = start or d_start, end or d_end
    window = {"start": start, "end": end}
    args = ["issues", "--json", "--start", start, "--end", end] + (["--by-store"] if by_store else [])
    try:
        out = _run_json(settings.pya_cli, args, settings.pya_cli_cwd, 120)
    except CliError as exc:
        return {**base, "source": "live", "complaint_tiles": None, **_source_error(exc)}
    tiles = [normalize_issue_tile(t, window) for t in out.data if isinstance(t, dict)] if isinstance(out.data, list) else []
    return {**base, "source": "live", "fetched_at": iso_chile(), "status": "ok", "error": None,
            "window": window, "complaint_tiles": tiles}


@router.get("/api/disputes")
async def list_disputes(request: Request, platform: str = "uber", status: str = "pending", live: bool = False,
                        start: str | None = None, end: str | None = None, store_id: str | None = None,
                        by_store: bool = False, limit: int = 500):
    operator(request)
    settings = get_settings()
    start, end, store_id = _check_date(start, "start"), _check_date(end, "end"), _check_store(store_id)
    if platform == "uber":
        if status not in UBER_STATUSES:
            raise HTTPException(status_code=400, detail="status inválido")
        if not live:
            return _uber_list_snapshot(settings)
        return await asyncio.to_thread(_uber_list_live, settings, status, start, end, store_id, max(1, min(limit, 1000)))
    if platform == "pedidosya":
        return await asyncio.to_thread(_pya_list, settings, live, start, end, by_store)
    if platform == "rappi":
        return {"platform": "rappi", "status": "pending", "disputes": None,
                "error": "Rappi pendiente: sin CLI ni credenciales. No se muestran cifras."}
    raise HTTPException(status_code=400, detail="Plataforma inválida")


# ---------- detalle Uber ----------

def _uber_fetch_photos(settings: Settings, order_id: str, store_id: str | None) -> dict:
    ref = _uber_ref(settings, order_id)
    store_id = store_id or ref.get("restaurant_uuid")
    tmp = Path(tempfile.mkdtemp(prefix="uber-fotos-"))
    try:
        args = ["dispute-photos", order_id, "--json", "--out", str(tmp)]
        if store_id:
            args += ["--id", store_id]
        out = _run_json(settings.uber_cli, args, settings.uber_cli_cwd, DETAIL_TIMEOUT)
        rows = out.data if isinstance(out.data, list) else []
        row = next((r for r in rows if isinstance(r, dict) and str(r.get("order")) == order_id), None)
        if not row:
            return {"status": "error", "auth": False, "error": "uber.py no devolvió el pedido"}
        if row.get("error"):
            return {"status": "not_found", "auth": False,
                    "error": "Uber no encontró el pedido en la ventana de 30 días" + ("" if store_id else " (sin tienda: se buscó en todas)")}
        folder = tmp / order_id
        failed = 0
        try:
            detail = json.loads((folder / "detalle.json").read_text(encoding="utf-8"))
            failed = sum(1 for f in detail.get("files") or [] if isinstance(f, dict) and not f.get("path"))
        except (OSError, json.JSONDecodeError):
            pass
        media.replace_group(settings.media_dir, "uber", order_id, "cliente", folder / "cliente")
        media.replace_group(settings.media_dir, "uber", order_id, "tienda", folder / "tienda")
        meta = {
            "order": order_id,
            "store": row.get("store"),
            "tag": row.get("tag"),
            "issue": row.get("issue"),
            "customer_comment": sanitize(row.get("comentario_cliente"), 2000),
            "ai_explanation": sanitize(row.get("ia"), 2000),
            "dispute_status": row.get("disputa"),
            "dispute_reason": row.get("motivo"),
            "dispute_description": sanitize(row.get("descripcion"), 1000),
            "customer_images": row.get("fotos_cliente"),
            "store_evidence": row.get("evidencia_tienda"),
            "downloads_failed": failed,
            "fetched_at": iso_chile(),
        }
        media.set_meta(settings.media_dir, "uber", order_id, meta)
        return {"status": "ok", "auth": False, "error": None}
    except CliError as exc:
        return _source_error(exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _uber_detail(settings: Settings, order_id: str, store_id: str | None, refresh: bool) -> dict:
    meta = media.get_meta(settings.media_dir, "uber", order_id)
    fetch = {"status": "cached", "auth": False, "error": None}
    if refresh or not meta:
        if not has_session(settings, "uber"):
            fetch = _missing("uber")
        else:
            fetch = _uber_fetch_photos(settings, order_id, store_id)
            meta = media.get_meta(settings.media_dir, "uber", order_id) or meta
    ref = _uber_ref(settings, order_id)
    row = next((d for d in _raw_snapshot(settings).get("disputes") or []
                if isinstance(d, dict) and str(d.get("order_id")) == order_id), None)
    return {
        "platform": "uber",
        "order_id": order_id,
        "platform_fetch": fetch,
        "meta": meta,
        "charge": _public_dispute(row) if row else None,
        "platform_media": _media_view(settings, "uber", order_id),
        "app_evidence": evidence.list_images(settings, "uber", order_id),
        "submit": {
            "can_prepare": bool(ref.get("workflow_uuid") and ref.get("restaurant_uuid")),
            "missing": [k for k in ("workflow_uuid", "restaurant_uuid") if not ref.get(k)],
            "real_submit_enabled": _allow_real_submit(),
            "verified_live": False,
            "reasons": list(UBER_REASONS),
            "note": UNVERIFIED,
        },
    }


@router.get("/api/disputes/uber/{order_id}")
async def uber_detail(request: Request, order_id: str, store_id: str | None = None, refresh: bool = False):
    operator(request)
    return await asyncio.to_thread(_uber_detail, get_settings(), _order(order_id), _check_store(store_id), refresh)


# ---------- envío de disputa ----------

def _collect_evidence(settings: Settings, order_id: str, media_ids: list[str], app_ids: list[str], folder: Path) -> list[Path]:
    files: list[Path] = []
    for mid in media_ids:
        try:
            path, _ = media.find(settings.media_dir, "uber", order_id, str(mid))
        except (media.MediaError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail="Una evidencia elegida no existe en el panel") from exc
        if path.suffix.lower() not in EVIDENCE_EXT:
            raise HTTPException(status_code=400, detail="Formato de evidencia no aceptado por Uber (jpg, png, mp4, pdf)")
        dest = folder / f"evidencia-{len(files) + 1}{path.suffix.lower()}"
        shutil.copyfile(path, dest)
        files.append(dest)
    for image_id in app_ids:
        try:
            data, ctype = evidence.fetch_image(settings, "uber", order_id, str(image_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail="Una foto de la app ya no está en la API de evidencia") from exc
        except evidence.EvidenceError as exc:
            raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
        ext = ".png" if ctype == "image/png" else ".jpg"
        dest = folder / f"evidencia-{len(files) + 1}{ext}"
        dest.write_bytes(data)
        files.append(dest)
    if sum(f.stat().st_size for f in files) > MAX_EVIDENCE_BYTES:
        raise HTTPException(status_code=400, detail="La evidencia supera 100 MB")
    return files


def _uber_submit(settings: Settings, user: str, order_id: str, body: dict) -> dict:
    confirm = body.get("confirm") is True
    reason = str(body.get("reason") or "")
    description = str(body.get("description") or "").strip()[:2000]
    media_ids = [str(x) for x in body.get("evidence_ids") or []]
    app_ids = [str(x) for x in body.get("app_evidence_ids") or []]
    if reason not in UBER_REASONS:
        raise HTTPException(status_code=400, detail="Motivo inválido")
    if reason == "OTHER" and not description:
        raise HTTPException(status_code=400, detail="El motivo OTHER exige una descripción")
    if len(media_ids) + len(app_ids) > MAX_EVIDENCE:
        raise HTTPException(status_code=400, detail="Uber acepta como máximo 3 archivos de evidencia")
    if confirm and not _allow_real_submit():
        audit(user, "disputes.uber.submit", order_id, False, "bloqueado", "ALLOW_UBER_DISPUTE_SUBMIT apagado")
        raise HTTPException(status_code=403, detail=(
            "Envío real deshabilitado: falta autorización del dueño para una prueba en vivo "
            "(ALLOW_UBER_DISPUTE_SUBMIT=true en el servidor). Use la preparación en dry-run."
        ))
    if not has_session(settings, "uber"):
        raise HTTPException(status_code=409, detail="Sin sesión de Uber: cárguela en Credenciales")
    ref = _uber_ref(settings, order_id)
    if not ref.get("workflow_uuid") or not ref.get("restaurant_uuid"):
        raise HTTPException(status_code=409, detail=(
            "Faltan datos internos del cobro (workflow o tienda). Consulte los cobros de Uber "
            "y actualice el snapshot antes de preparar la disputa."
        ))
    folder = Path(tempfile.mkdtemp(prefix="uber-disputa-"))
    try:
        files = _collect_evidence(settings, order_id, media_ids, app_ids, folder)
        args = ["dispute", "--workflow", ref["workflow_uuid"], "--restaurant", ref["restaurant_uuid"],
                "--reason", reason, "--description", description]
        if files:
            args += ["--evidence", *[str(f) for f in files]]
        args.append("--yes" if confirm else "--dry-run")
        with _cli_slots:
            proc = run_cli(settings.uber_cli, args, settings.uber_cli_cwd, SUBMIT_TIMEOUT)
    except CliError as exc:
        audit(user, "disputes.uber.submit", order_id, not confirm, "error", str(exc))
        raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    if proc.returncode != 0:
        msg = sanitize((stderr.strip().splitlines() or [stdout.strip()])[-1] if (stderr or stdout).strip() else f"exit {proc.returncode}")
        auth = looks_like_auth_failure(stdout + stderr)
        audit(user, "disputes.uber.submit", order_id, not confirm, "error", msg)
        raise HTTPException(status_code=502,
                            detail=("Uber rechazó la sesión. " if auth else "") + (msg or "uber.py dispute falló"))
    if not confirm:
        try:
            plan = json.loads(stdout)
        except json.JSONDecodeError:
            plan = {"raw": sanitize(stdout, 1500)}
        for ev in plan.get("evidence_files") or []:
            if isinstance(ev, dict) and ev.get("path"):
                ev["path"] = os.path.basename(str(ev["path"]))
        audit(user, "disputes.uber.submit", order_id, True, "dry-run",
              f"problemas={len(plan.get('problems') or [])} evidencia={len(files)}")
        return {"dry_run": True, "verified": False, "note": UNVERIFIED, "results": [{
            "order": plan.get("order") or order_id,
            "store": plan.get("store"),
            "eligibility": plan.get("eligibility"),
            "problems": plan.get("problems") or [],
            "transport": plan.get("transport"),
            "evidence_files": plan.get("evidence_files") or [],
            "payload": (plan.get("variables") or {}).get("disputeSubmission"),
        }]}
    answer = sanitize(stdout, 1500)
    audit(user, "disputes.uber.submit", order_id, False, "enviado (no verificado)", answer)
    return {"dry_run": False, "verified": False, "note": UNVERIFIED,
            "results": [{"order": order_id, "uber_response": answer}]}


@router.post("/api/disputes/uber/{order_id}/submit")
async def uber_submit(request: Request, order_id: str, body: dict = Body(...)):
    user = operator(request)
    return await asyncio.to_thread(_uber_submit, get_settings(), user, _order(order_id), body or {})


@router.post("/api/disputes/pedidosya/{order_id}/submit")
async def pya_submit(request: Request, order_id: str):
    user = operator(request)
    audit(user, "disputes.pedidosya.submit", order_id, True, "501 no disponible")
    raise HTTPException(status_code=501, detail=PYA_SUBMIT_501)


# ---------- pedido PedidosYa ----------

def _pya_public_order(raw: dict) -> dict:
    o = raw.get("order") if isinstance(raw.get("order"), dict) else raw
    inner = o.get("order") if isinstance(o.get("order"), dict) else {}
    items = []
    for it in inner.get("items") or []:
        if isinstance(it, dict):
            items.append({
                "name": it.get("name"),
                "quantity": it.get("quantity"),
                "unit_price": it.get("unitPrice"),
                "options": [op.get("name") for op in it.get("options") or [] if isinstance(op, dict)],
            })
    issues = []
    for iss in o.get("orderIssues") or []:
        if isinstance(iss, dict):
            md = iss.get("metadata") or {}
            issues.append({"issue": iss.get("orderIssue"), "reason": md.get("reason"), "amount": md.get("amount")})
    refunds = []
    for rf in ((o.get("refundData") or {}).get("refunds") or []):
        if isinstance(rf, dict):
            refunds.append({"amount": rf.get("amount"), "status": rf.get("status"), "issue": rf.get("issue"),
                            "items": [i.get("name") for i in rf.get("items") or [] if isinstance(i, dict)]})
    value = parse_clp(inner.get("orderValue"))
    return {
        "order_id": inner.get("orderId"),
        "placed": parse_requested(inner.get("placedTimestamp")),
        "status": inner.get("status"),
        "vendor_name": inner.get("vendorName"),
        "order_value": value,
        "order_value_display": format_clp(value) if value is not None else None,
        "items": items,
        "is_dispute_allowed": o.get("isDisputeAllowed"),
        "dispute_status": (o.get("dispute") or {}).get("status") if isinstance(o.get("dispute"), dict) else None,
        "order_issues": issues,
        "refunds": refunds,
    }


def _pya_order(settings: Settings, order_id: str, store_id: str, photos: bool,
               start: str | None, end: str | None) -> dict:
    base = {"platform": "pedidosya", "order_id": order_id, "store_id": store_id,
            "dispute_submit": {"available": False, "note": PYA_SUBMIT_501}}
    fetch: dict
    order = None
    pictures = None
    if not has_session(settings, "pedidosya"):
        fetch = _missing("pedidosya")
    else:
        tmp = Path(tempfile.mkdtemp(prefix="pya-fotos-"))
        try:
            args = ["order", order_id, "--id", store_id, "--json"]
            if start:
                args += ["--start", start]
            if end:
                args += ["--end", end]
            if photos:
                args += ["--photos", "--download", str(tmp)]
            out = _run_json(settings.pya_cli, args, settings.pya_cli_cwd, DETAIL_TIMEOUT)
            raw = out.data if isinstance(out.data, dict) else {}
            order = _pya_public_order(raw)
            if photos:
                pics = raw.get("orderIssuePictures") if isinstance(raw.get("orderIssuePictures"), dict) else {}
                urls = pics.get("urls") or []
                files = pics.get("files") or []
                media.replace_group(settings.media_dir, "pedidosya", order_id, "cliente", tmp)
                pictures = {"count": len(urls), "downloaded": sum(1 for f in files if isinstance(f, dict) and f.get("file")),
                            "failed": sum(1 for f in files if isinstance(f, dict) and not f.get("file"))}
                media.set_meta(settings.media_dir, "pedidosya", order_id,
                               {"order": order, "pictures": pictures, "fetched_at": iso_chile()})
            fetch = {"status": "ok", "auth": False, "error": None}
        except CliError as exc:
            fetch = _source_error(exc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if order is None:
        cached = media.get_meta(settings.media_dir, "pedidosya", order_id) or {}
        order, pictures = cached.get("order"), cached.get("pictures")
    return {
        **base,
        "platform_fetch": fetch,
        "order": order,
        "pictures": pictures,
        "platform_media": _media_view(settings, "pedidosya", order_id),
        "app_evidence": evidence.list_images(settings, "pedidosya", order_id),
    }


@router.get("/api/orders/pedidosya/{order_id}")
async def pya_order(request: Request, order_id: str, store_id: str | None = None, photos: bool = False,
                    start: str | None = None, end: str | None = None):
    operator(request)
    order_id = _order(order_id)
    store_id = _check_store(store_id)
    if not store_id:
        raise HTTPException(status_code=400, detail="Elija la tienda de PedidosYa (store_id): pya.py order necesita el local")
    return await asyncio.to_thread(_pya_order, get_settings(), order_id, store_id, photos,
                                   _check_date(start, "start"), _check_date(end, "end"))


# ---------- media de plataforma ----------

def _serve(platform: str, order_id: str, media_id: str):
    settings = get_settings()
    try:
        path, item = media.find(settings.media_dir, platform, _order(order_id), media_id)
    except media.MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from exc
    ctype = item.get("content_type") or "application/octet-stream"
    inline = ctype.startswith("image/") or ctype.startswith("video/")
    return FileResponse(
        path,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=120",
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{media_id}"',
        },
    )


@router.get("/api/disputes/uber/{order_id}/media/{media_id}")
async def uber_media(request: Request, order_id: str, media_id: str):
    operator(request)
    return _serve("uber", order_id, media_id)


@router.get("/api/orders/pedidosya/{order_id}/media/{media_id}")
async def pya_media(request: Request, order_id: str, media_id: str):
    operator(request)
    return _serve("pedidosya", order_id, media_id)


@router.patch("/api/media/{platform}/{order_id}/{media_id}")
async def mark_media(request: Request, platform: str, order_id: str, media_id: str, body: dict = Body(...)):
    user = operator(request)
    settings = get_settings()
    try:
        item = media.set_sensitive(settings.media_dir, platform, _order(order_id), media_id, bool((body or {}).get("sensitive")))
    except media.MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from exc
    audit(user, "media.sensitive", f"{platform}/{order_id}/{media_id}", False, "ok", f"sensitive={item['sensitive']}")
    return {"ok": True, "item": item}


# ---------- fotos de la app delivery ----------

@router.get("/api/evidence/{agregador}")
async def app_evidence(request: Request, agregador: str, numero_orden: str = ""):
    operator(request)
    try:
        result = await asyncio.to_thread(evidence.list_images, get_settings(), agregador, numero_orden)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"agregador": agregador, "numero_orden": numero_orden.strip(), **result}


@router.get("/api/evidence/{agregador}/media/{image_id}")
async def app_evidence_media(request: Request, agregador: str, image_id: str, numero_orden: str = ""):
    operator(request)
    try:
        data, ctype = await asyncio.to_thread(evidence.fetch_image, get_settings(), agregador, numero_orden, image_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Foto no encontrada en la API de evidencia") from exc
    except evidence.EvidenceError as exc:
        raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
    return Response(content=data, media_type=ctype, headers={
        "Cache-Control": "private, max-age=120",
        "Content-Disposition": 'inline; filename="evidencia.jpg"',
    })
