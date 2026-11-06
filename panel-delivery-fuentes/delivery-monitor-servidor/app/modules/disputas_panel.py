"""Panel exclusivo de disputas: estadísticas, listado por estado y armado de la solicitud por pedido.

- Uber: los estados salen del orderTag de Uber (pendiente, abierta, ganada, perdida).
- PedidosYa: no hay disputas por API. Las cifras salen de `issues` (problemas de pedidos) y el estado
  de cada reclamo lo lleva el registro local del panel (preparada → abierta → ganada / perdida).
- Las fotos de la tienda salen de la API de evidencia (app delivery) por número de pedido.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, Request

from delivery_monitor.adapters.runner import CliError, run_json_cli
from delivery_monitor.adapters.uber import dispute_outcome, normalize_dispute, parse_counters
from delivery_monitor.parseutil import format_clp, iso_chile, parse_clp, parse_requested
from delivery_monitor.sanitize import sanitize

from ..config import Settings
from ..deps import audit, get_settings, operator
from . import disputes, evidence, media
from .credentials import has_session

router = APIRouter(prefix="/api/panel")

TZ = ZoneInfo("America/Santiago")
PLATFORMS = ("uber", "pedidosya")
STATES = ("pendiente", "abierta", "ganada", "perdida")
LOCAL_STATES = ("preparada", "abierta", "ganada", "perdida")
UBER_STATUSES = ("pending", "accepted", "rejected", "disputed")
UBER_TIMEOUT = int(os.environ.get("PANEL_UBER_TIMEOUT", "600"))
PYA_TIMEOUT = int(os.environ.get("PANEL_PYA_TIMEOUT", "900"))
UBER_MAX = 2000

UBER_REASON_LABELS = {
    "STORE_EVIDENCE_AVAILABLE": "La tienda tiene evidencia (fotos del pedido)",
    "CUSTOMER_MISTAKE": "Error del cliente",
    "CUSTOMER_PROVIDED_EVIDENCE_INCORRECT": "La evidencia del cliente es incorrecta",
    "DELIVERY_DRIVER_RELATED": "Problema del repartidor",
    "EVIDENCE_UNCONVINCING": "La evidencia del cliente no convence",
    "INCORRECT_REFUND_AMOUNT": "Monto de reembolso incorrecto",
    "OTHER": "Otro (requiere descripción)",
}
PYA_REASON_LABELS = {
    "PEDIDO_COMPLETO": "El pedido salió completo (hay foto)",
    "PRODUCTO_CORRECTO": "El producto entregado es el correcto",
    "REPARTIDOR": "Problema del repartidor",
    "ERROR_CLIENTE": "Error del cliente",
    "MONTO_INCORRECTO": "El monto descontado es incorrecto",
    "OTRO": "Otro",
}
PYA_TILE_LABELS = {
    "CUSTOMER_COMPLAINTS": "Reclamos de clientes",
    "ORDERS_WITH_DEDUCTION": "Pedidos con descuento",
    "AVOIDABLE_CANCELLATIONS": "Cancelaciones evitables",
    "AVOIDABLE_WAIT_TIME": "Espera evitable del repartidor",
    "ALL": "Todos los problemas",
}
PYA_BLOCKED = (
    "PedidosYa bloqueó el listado por pedido desde este servidor (protección anti-bots, HTTP 403). "
    "Las cifras de arriba sí están al día. Use «Buscar imagen manual» con el número de pedido."
)

_lock = threading.Lock()
_jobs: dict[str, dict] = {p: {"running": False} for p in PLATFORMS}


# ---------- archivos ----------

def _cache_path(settings: Settings) -> Path:
    return settings.data_dir / "disputas_cache.json"


def _registry_path(settings: Settings) -> Path:
    return settings.data_dir / "disputas_registro.json"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _platform(value: str) -> str:
    if value not in PLATFORMS:
        raise HTTPException(status_code=400, detail="platform debe ser uber o pedidosya")
    return value


def _order(value: str) -> str:
    try:
        return media.valid_order(evidence.normalize_order(value))
    except (media.MediaError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Número de pedido inválido") from exc


def _window(days: int) -> tuple[str, str]:
    days = max(1, min(int(days), 30))
    today = dt.datetime.now(TZ).date()
    return str(today - dt.timedelta(days=days - 1)), str(today)


# ---------- consulta a las plataformas ----------

def _uber_query(settings: Settings, status: str, start: str, end: str) -> tuple[list[dict], str]:
    out = run_json_cli(settings.uber_cli, ["disputes", "--json", "--status", status, "--start", start,
                                           "--end", end, "--max", str(UBER_MAX)],
                       settings.uber_cli_cwd, UBER_TIMEOUT)
    return (out.data if isinstance(out.data, list) else []), out.stderr or ""


def refresh_uber(settings: Settings, days: int) -> dict:
    start, end = _window(days)
    window = {"start": start, "end": end, "label": f"{start} a {end} (America/Santiago)"}
    if not has_session(settings, "uber"):
        return {"status": "missing_credentials", "error": "Sin sesión de Uber: cárguela en Credenciales.",
                "window": window, "fetched_at": iso_chile(), "rows": None, "counters": None}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {s: pool.submit(_uber_query, settings, s, start, end) for s in UBER_STATUSES}
        results, errors = {}, []
        for s, fut in futures.items():
            try:
                results[s] = fut.result()
            except CliError as exc:
                errors.append((s, exc))
    if errors and not results:
        exc = errors[0][1]
        return {"status": "error", "auth": bool(exc.auth), "error": sanitize(str(exc)), "window": window,
                "fetched_at": iso_chile(), "rows": None, "counters": None}
    rows: dict[str, dict] = {}
    counters = None
    for s in UBER_STATUSES:
        data, stderr = results.get(s, ([], ""))
        counters = counters or parse_counters(stderr)[0]
        for raw in data:
            if not isinstance(raw, dict):
                continue
            row = normalize_dispute(raw, window)
            row["outcome"] = dispute_outcome(row.get("tag") or "")
            if row["order_id"]:
                rows[row["order_id"]] = row
    ordered = sorted(rows.values(), key=lambda r: r.get("ordered_at") or "", reverse=True)
    disputes._remember_uber(settings, ordered)
    partial = [s for s, _ in errors]
    return {"status": "partial" if partial else "ok", "error": (
        "Uber no respondió para: " + ", ".join(partial)) if partial else None,
        "window": window, "fetched_at": iso_chile(), "rows": ordered, "counters": counters}


def _pya_vendor_ids(settings: Settings) -> dict[str, str]:
    snap = disputes._raw_snapshot(settings)
    return {str(s.get("name")): str(s.get("store_id")) for s in snap.get("stores") or []
            if isinstance(s, dict) and s.get("platform") == "pedidosya" and s.get("store_id")}


def _parse_pya_issues(text: str) -> list[dict]:
    out = []
    for part in (text or "").split("; "):
        if not part:
            continue
        bits = part.split(":")
        kind = bits[0]
        reason = bits[1] if len(bits) > 1 else ""
        amount = parse_clp(bits[2]) if len(bits) > 2 and bits[2] else None
        out.append({"type": kind, "reason": reason or None, "amount_clp": amount})
    return out


def refresh_pya(settings: Settings, days: int) -> dict:
    start, end = _window(days)
    window = {"start": start, "end": end, "label": f"{start} a {end} (America/Santiago)"}
    base = {"window": window, "fetched_at": iso_chile()}
    if not has_session(settings, "pedidosya"):
        return {**base, "status": "missing_credentials", "error": "Sin sesión de PedidosYa: cárguela en Credenciales.",
                "tiles": None, "orders": None, "orders_status": "missing_credentials", "orders_error": None}
    try:
        out = run_json_cli(settings.pya_cli, ["issues", "--json", "--start", start, "--end", end],
                           settings.pya_cli_cwd, PYA_TIMEOUT)
        tiles = [{
            "type": t.get("type"), "label": PYA_TILE_LABELS.get(str(t.get("type")), t.get("type")),
            "orders": t.get("orders"), "amount_clp": parse_clp(t.get("amount")),
            "amount_type": t.get("amount_type"), "orders_with_amount": t.get("orders_with_amount"),
        } for t in (out.data if isinstance(out.data, list) else []) if isinstance(t, dict)]
        status, error = "ok", None
    except CliError as exc:
        tiles, status, error = None, "error", sanitize(str(exc))
    orders, orders_status, orders_error = None, "ok", None
    try:
        out = run_json_cli(settings.pya_cli, ["orders", "--issues", "--json", "--start", start, "--end", end],
                           settings.pya_cli_cwd, PYA_TIMEOUT)
        vendors = _pya_vendor_ids(settings)
        orders = []
        for r in out.data if isinstance(out.data, list) else []:
            if not isinstance(r, dict) or not r.get("order_id"):
                continue
            issues = _parse_pya_issues(str(r.get("issues") or ""))
            deduction = parse_clp(r.get("fees_deductions"))
            orders.append({
                "platform": "pedidosya", "order_id": str(r["order_id"]), "store_name": r.get("store"),
                "store_id": vendors.get(str(r.get("store"))), "ordered_at": parse_requested(r.get("placed")) or r.get("placed"),
                "order_status": r.get("status"), "issues": issues,
                "issue": ", ".join(sorted({i["type"] for i in issues})) or None,
                "amount_clp": abs(deduction) if deduction is not None else None,
            })
    except CliError as exc:
        text = str(exc)
        blocked = "perimeterx" in text.lower() or "403" in text
        orders_status = "blocked" if blocked else "error"
        orders_error = PYA_BLOCKED if blocked else sanitize(text)
    return {**base, "status": status, "error": error, "tiles": tiles, "orders": orders,
            "orders_status": orders_status, "orders_error": orders_error}


def _run_refresh(platform: str, days: int, actor: str) -> None:
    settings = get_settings()
    try:
        data = refresh_uber(settings, days) if platform == "uber" else refresh_pya(settings, days)
        data["days"] = days
        with _lock:
            cache = _read(_cache_path(settings))
            cache[platform] = data
            _write(_cache_path(settings), cache)
        audit(actor, f"panel.refresh.{platform}", platform, False, data.get("status") or "ok", data.get("error"))
        result = {"status": data.get("status"), "error": data.get("error")}
    except Exception as exc:
        result = {"status": "error", "error": sanitize(str(exc))}
        audit(actor, f"panel.refresh.{platform}", platform, False, "error", str(exc))
    with _lock:
        _jobs[platform] = {"running": False, "finished_at": iso_chile(), **result}


# ---------- registro local ----------

def _registry(settings: Settings) -> dict:
    return _read(_registry_path(settings))


def _record(settings: Settings, platform: str, order_id: str, actor: str, **fields) -> dict:
    with _lock:
        reg = _registry(settings)
        key = f"{platform}:{order_id}"
        entry = reg.get(key) or {"platform": platform, "order_id": order_id, "created_at": iso_chile(), "history": []}
        state = fields.get("state")
        for k, v in fields.items():
            if v is not None:
                entry[k] = v
        entry["updated_at"] = iso_chile()
        entry["updated_by"] = actor
        if state:
            entry["history"] = (entry.get("history") or [])[-30:] + [{"at": iso_chile(), "state": state, "by": actor}]
        reg[key] = entry
        _write(_registry_path(settings), reg)
    return entry


def _public_record(entry: dict | None) -> dict | None:
    if not entry:
        return None
    return {k: entry.get(k) for k in (
        "state", "reason", "description", "evidence", "created_at", "updated_at", "history", "note",
    )}


# ---------- vistas ----------

def _public_row(row: dict, reg: dict | None) -> dict:
    out = {k: row.get(k) for k in (
        "platform", "order_id", "store_name", "store_id", "ordered_at", "amount_clp", "issue", "tag", "order_status",
    )}
    out["amount_display"] = format_clp(row["amount_clp"]) if row.get("amount_clp") is not None else row.get("amount_display")
    out["record"] = _public_record(reg)
    return out


def _uber_rows(settings: Settings) -> tuple[dict, list[dict]]:
    cache = _read(_cache_path(settings)).get("uber") or {}
    reg = _registry(settings)
    rows = []
    for r in cache.get("rows") or []:
        entry = reg.get(f"uber:{r.get('order_id')}")
        row = _public_row(r, entry)
        row["state"] = r.get("outcome") or dispute_outcome(r.get("tag") or "")
        if row["state"] == "pendiente" and entry and entry.get("state") == "abierta":
            row["state"] = "abierta"
        rows.append(row)
    return cache, rows


def _pya_rows(settings: Settings) -> tuple[dict, list[dict]]:
    cache = _read(_cache_path(settings)).get("pedidosya") or {}
    reg = _registry(settings)
    rows, seen = [], set()
    for r in cache.get("orders") or []:
        entry = reg.get(f"pedidosya:{r.get('order_id')}")
        row = _public_row(r, entry)
        row["state"] = _local_state(entry)
        rows.append(row)
        seen.add(r.get("order_id"))
    for key, entry in reg.items():
        if not key.startswith("pedidosya:") or entry.get("order_id") in seen:
            continue
        row = _public_row({"platform": "pedidosya", "order_id": entry.get("order_id"),
                           "store_name": entry.get("store_name"), "store_id": entry.get("store_id"),
                           "ordered_at": entry.get("ordered_at"), "amount_clp": entry.get("amount_clp"),
                           "issue": entry.get("issue")}, entry)
        row["state"] = _local_state(entry)
        row["manual"] = True
        rows.append(row)
    rows.sort(key=lambda r: r.get("ordered_at") or r.get("record", {}) and r["record"].get("updated_at") or "", reverse=True)
    return cache, rows


def _local_state(entry: dict | None) -> str:
    state = (entry or {}).get("state")
    return state if state in ("abierta", "ganada", "perdida") else "pendiente"


def _summary(rows: list[dict]) -> dict:
    out = {}
    for s in STATES:
        sel = [r for r in rows if r.get("state") == s]
        amount = sum(r.get("amount_clp") or 0 for r in sel)
        out[s] = {"count": len(sel), "amount_clp": amount, "amount_display": format_clp(amount)}
    return out


def _top(rows: list[dict], key: str, n: int = 5) -> list[dict]:
    c = Counter(r.get(key) for r in rows if r.get(key))
    return [{"name": k, "count": v} for k, v in c.most_common(n)]


def _stats(settings: Settings, platform: str) -> dict:
    job = dict(_jobs.get(platform) or {})
    if platform == "uber":
        cache, rows = _uber_rows(settings)
        by_state = _summary(rows)
        decided = by_state["ganada"]["count"] + by_state["perdida"]["count"]
        pending = [r for r in rows if r["state"] == "pendiente"]
        reg = _registry(settings)
        return {
            "platform": "uber", "fetched_at": cache.get("fetched_at"), "window": cache.get("window"),
            "status": cache.get("status") or "pending", "error": cache.get("error"), "refresh": job,
            "by_state": by_state,
            "success_rate": round(100 * by_state["ganada"]["count"] / decided) if decided else None,
            "uber_counters": cache.get("counters"),
            "prepared": sum(1 for k, v in reg.items() if k.startswith("uber:") and v.get("state") == "preparada"),
            "top_stores_pending": _top(pending, "store_name"),
            "by_issue": _top(rows, "issue", 6),
        }
    cache, rows = _pya_rows(settings)
    by_state = _summary(rows)
    decided = by_state["ganada"]["count"] + by_state["perdida"]["count"]
    return {
        "platform": "pedidosya", "fetched_at": cache.get("fetched_at"), "window": cache.get("window"),
        "status": cache.get("status") or "pending", "error": cache.get("error"), "refresh": job,
        "tiles": cache.get("tiles"),
        "orders_status": cache.get("orders_status"), "orders_error": cache.get("orders_error"),
        "by_state": by_state,
        "success_rate": round(100 * by_state["ganada"]["count"] / decided) if decided else None,
        "top_stores_problems": _top(rows, "store_name"),
        "note": "PedidosYa no tiene disputas por API: abiertas, ganadas y perdidas salen del registro de este panel.",
    }


# ---------- rutas ----------

@router.get("/meta")
async def meta(request: Request):
    operator(request)
    settings = get_settings()
    return {
        "platforms": [{"id": "uber", "label": "Uber Eats"}, {"id": "pedidosya", "label": "PedidosYa"}],
        "states": [{"id": "pendiente", "label": "Pendientes"}, {"id": "abierta", "label": "Abiertas"},
                   {"id": "ganada", "label": "Cerradas ganadas"}, {"id": "perdida", "label": "Cerradas perdidas"}],
        "reasons": {"uber": UBER_REASON_LABELS, "pedidosya": PYA_REASON_LABELS},
        "max_evidence": {"uber": disputes.MAX_EVIDENCE, "pedidosya": 10},
        "uber_real_submit": disputes._allow_real_submit(),
        "login": settings.auth_required,
        "timezone": "America/Santiago",
    }


@router.get("/stats")
async def stats(request: Request, platform: str = "uber"):
    operator(request)
    return _stats(get_settings(), _platform(platform))


@router.get("/disputes")
async def list_disputes(request: Request, platform: str = "uber", estado: str = "pendiente", q: str = ""):
    operator(request)
    settings = get_settings()
    platform = _platform(platform)
    if estado not in (*STATES, "todas"):
        raise HTTPException(status_code=400, detail="estado debe ser pendiente, abierta, ganada, perdida o todas")
    cache, rows = _uber_rows(settings) if platform == "uber" else _pya_rows(settings)
    if estado != "todas":
        rows = [r for r in rows if r.get("state") == estado]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in str(r.get("order_id") or "").lower()
                or needle in str(r.get("store_name") or "").lower()]
    return {"platform": platform, "estado": estado, "count": len(rows), "rows": rows[:1000],
            "truncated": len(rows) > 1000, "fetched_at": cache.get("fetched_at"), "window": cache.get("window"),
            "status": cache.get("status") or "pending", "error": cache.get("error"),
            "orders_status": cache.get("orders_status"), "orders_error": cache.get("orders_error")}


@router.post("/refresh")
async def refresh(request: Request, body: dict = Body(default={})):
    actor = operator(request)
    platform = _platform(str((body or {}).get("platform") or ""))
    try:
        days = int((body or {}).get("days") or (30 if platform == "uber" else 7))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="days debe ser un entero") from exc
    with _lock:
        if _jobs[platform].get("running"):
            return {"started": False, "running": True, **_jobs[platform]}
        _jobs[platform] = {"running": True, "started_at": iso_chile(), "days": days}
    threading.Thread(target=_run_refresh, args=(platform, days, actor), daemon=True).start()
    return {"started": True, "running": True, "days": days}


@router.get("/refresh")
async def refresh_status(request: Request, platform: str = "uber"):
    operator(request)
    with _lock:
        return dict(_jobs[_platform(platform)])


def _order_view(settings: Settings, platform: str, order_id: str) -> dict:
    cache, rows = _uber_rows(settings) if platform == "uber" else _pya_rows(settings)
    row = next((r for r in rows if r.get("order_id") == order_id), None)
    entry = _registry(settings).get(f"{platform}:{order_id}")
    view = {
        "platform": platform,
        "order_id": order_id,
        "row": row,
        "record": _public_record(entry),
        "app_evidence": evidence.list_images(settings, platform, order_id),
        "platform_media": disputes._media_view(settings, platform, order_id),
        "reasons": UBER_REASON_LABELS if platform == "uber" else PYA_REASON_LABELS,
    }
    if platform == "uber":
        ref = disputes._uber_ref(settings, order_id)
        view["submit"] = {
            "can_prepare": bool(ref.get("workflow_uuid") and ref.get("restaurant_uuid")),
            "missing_note": None if ref.get("workflow_uuid") and ref.get("restaurant_uuid") else (
                "Este pedido no aparece entre los cobros de Uber guardados. Actualice Uber (botón «Actualizar») "
                "o revise el número: Uber solo permite disputar cobros de los últimos 30 días."),
            "real_submit_enabled": disputes._allow_real_submit(),
            "max_evidence": disputes.MAX_EVIDENCE,
            "note": disputes.UNVERIFIED,
        }
    else:
        view["submit"] = {"can_prepare": True, "real_submit_enabled": False, "max_evidence": 10,
                          "note": disputes.PYA_SUBMIT_501}
    return view


@router.get("/order/{platform}/{order_id}")
async def order_view(request: Request, platform: str, order_id: str):
    operator(request)
    return await asyncio.to_thread(_order_view, get_settings(), _platform(platform), _order(order_id))


def _pya_package(settings: Settings, order_id: str, body: dict, row: dict | None) -> dict:
    reason = str(body.get("reason") or "")
    if reason not in PYA_REASON_LABELS:
        raise HTTPException(status_code=400, detail="Motivo inválido para PedidosYa")
    description = str(body.get("description") or "").strip()[:2000]
    if reason == "OTRO" and not description:
        raise HTTPException(status_code=400, detail="El motivo «Otro» exige una descripción")
    app_ids = [str(x) for x in body.get("app_evidence_ids") or []][:10]
    media_ids = [str(x) for x in body.get("evidence_ids") or []][:10]
    images = {i["id"]: i for i in (evidence.list_images(settings, "pedidosya", order_id).get("images") or [])}
    missing = [i for i in app_ids if i not in images]
    if missing:
        raise HTTPException(status_code=400, detail="Una foto elegida ya no está en la API de evidencia")
    platform_media = {m["id"]: m for m in disputes._media_view(settings, "pedidosya", order_id)}
    evidence_list = [{"origen": "app delivery", "id": i, "url": images[i]["url"], "tomada": images[i].get("created_at")}
                     for i in app_ids]
    evidence_list += [{"origen": "PedidosYa", "id": m, "url": platform_media[m]["url"]} for m in media_ids if m in platform_media]
    store = (row or {}).get("store_name") or body.get("store_name")
    amount = (row or {}).get("amount_clp")
    issue = (row or {}).get("issue")
    lines = [
        f"Solicito revisar el reclamo del pedido N° {order_id}" + (f" del local {store}" if store else "") + ".",
        f"Motivo: {PYA_REASON_LABELS[reason]}.",
    ]
    if issue:
        lines.append(f"Problema informado: {issue}.")
    if amount:
        lines.append(f"Monto descontado: {format_clp(amount)}.")
    if description:
        lines.append(description)
    if evidence_list:
        lines.append(f"Adjunto {len(evidence_list)} foto(s) del pedido tomadas por el local antes del despacho.")
    return {
        "plataforma": "PedidosYa",
        "pedido": order_id,
        "tienda": store,
        "problema": issue,
        "monto_descontado_clp": amount,
        "motivo": reason,
        "motivo_texto": PYA_REASON_LABELS[reason],
        "descripcion": description,
        "evidencia": evidence_list,
        "texto_para_portal": "\n".join(lines),
        "como_enviar": "PedidosYa no recibe disputas por API: copie el texto en el Portal de Socios (Pedidos → "
                       "detalle del pedido → Ayuda) y adjunte las fotos. Luego marque «Enviada» en este panel.",
    }


def _build_request(settings: Settings, actor: str, platform: str, order_id: str, body: dict) -> dict:
    confirm = body.get("confirm") is True
    _, rows = _uber_rows(settings) if platform == "uber" else _pya_rows(settings)
    row = next((r for r in rows if r.get("order_id") == order_id), None)
    if platform == "uber":
        result = disputes._uber_submit(settings, actor, order_id, body)
        state = "abierta" if confirm else "preparada"
        entry = _record(settings, "uber", order_id, actor, state=state, reason=body.get("reason"),
                        description=str(body.get("description") or "")[:2000],
                        evidence=[*(body.get("app_evidence_ids") or []), *(body.get("evidence_ids") or [])][:3],
                        store_name=(row or {}).get("store_name"), amount_clp=(row or {}).get("amount_clp"))
        return {"platform": "uber", "order_id": order_id, "dry_run": not confirm, "result": result,
                "record": _public_record(entry)}
    package = _pya_package(settings, order_id, body, row)
    entry = _record(settings, "pedidosya", order_id, actor, state="preparada", reason=package["motivo"],
                    description=package["descripcion"], evidence=[e["id"] for e in package["evidencia"]],
                    store_name=package["tienda"], store_id=(row or {}).get("store_id"),
                    amount_clp=package["monto_descontado_clp"], issue=package["problema"],
                    ordered_at=(row or {}).get("ordered_at"))
    audit(actor, "panel.request.pedidosya", order_id, True, "preparada", f"evidencia={len(package['evidencia'])}")
    return {"platform": "pedidosya", "order_id": order_id, "dry_run": True, "request": package,
            "record": _public_record(entry)}


@router.post("/request/{platform}/{order_id}")
async def build_request(request: Request, platform: str, order_id: str, body: dict = Body(...)):
    actor = operator(request)
    return await asyncio.to_thread(_build_request, get_settings(), actor, _platform(platform), _order(order_id), body or {})


@router.post("/record/{platform}/{order_id}")
async def set_state(request: Request, platform: str, order_id: str, body: dict = Body(...)):
    actor = operator(request)
    platform, order_id = _platform(platform), _order(order_id)
    state = str((body or {}).get("state") or "")
    if platform == "uber" and state in ("ganada", "perdida"):
        raise HTTPException(status_code=400, detail="En Uber el resultado lo informa Uber: actualice para verlo")
    if state not in LOCAL_STATES:
        raise HTTPException(status_code=400, detail="state debe ser preparada, abierta, ganada o perdida")
    note = str((body or {}).get("note") or "").strip()[:500] or None
    entry = _record(get_settings(), platform, order_id, actor, state=state, note=note)
    audit(actor, f"panel.record.{platform}", order_id, False, state)
    return {"platform": platform, "order_id": order_id, "record": _public_record(entry)}
