"""Reportes: catálogo y ejecución vía CLI (solo lectura)."""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from delivery_monitor.adapters.runner import CliError, run_cli, run_json_cli
from delivery_monitor.sanitize import sanitize

from ..deps import audit, get_settings, operator
from .cli_helpers import require_platform, require_session, script_paths
from . import jobs

router = APIRouter(prefix="/api/reports")

REPORT_TIMEOUT = int(os.environ.get("REPORT_TIMEOUT", "600"))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CATALOG = [
    {"id": "stores_snapshot", "platform": "both", "title": "Tiendas (snapshot)", "params": [], "formats": ["json"]},
    {"id": "uber_disputes", "platform": "uber", "title": "Cobros / disputas Uber", "params": ["start", "end", "status"], "formats": ["json", "csv"]},
    {"id": "uber_sales", "platform": "uber", "title": "Ventas Uber", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "uber_soldout", "platform": "uber", "title": "Agotados Uber", "params": ["store"], "formats": ["json", "csv"]},
    {"id": "uber_hours", "platform": "uber", "title": "Horarios Uber", "params": ["days"], "formats": ["json", "csv"]},
    {"id": "pya_sales", "platform": "pedidosya", "title": "Ventas PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_soldout", "platform": "pedidosya", "title": "Agotados PedidosYa", "params": ["store"], "formats": ["json", "csv"]},
    {"id": "pya_reviews", "platform": "pedidosya", "title": "Reseñas PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_ratings", "platform": "pedidosya", "title": "Ratings PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_issues", "platform": "pedidosya", "title": "Reclamos PedidosYa (issues)", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_orders", "platform": "pedidosya", "title": "Pedidos PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_payouts", "platform": "pedidosya", "title": "Pagos PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_earnings", "platform": "pedidosya", "title": "Earnings PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
    {"id": "pya_invoices", "platform": "pedidosya", "title": "Facturas PedidosYa", "params": ["start", "end"], "formats": ["json", "csv"]},
]

PYA_VOS = [
    "performance", "performance/summary", "ops/summary", "dishes", "heatmap", "eod", "area",
    "avg_acceptance_time", "awt", "contact-rate", "customer_conversion", "customer_retention",
    "customers/summary", "offline_duration", "order_rejection", "orders-marked-as-ready",
    "out-of-stock", "prep_time",
]
for name in PYA_VOS:
    CATALOG.append({
        "id": f"pya_vos_{name.replace('/', '_')}",
        "platform": "pedidosya",
        "title": f"VOS {name}",
        "params": ["start", "end", "vos_name"],
        "formats": ["json", "csv"],
        "vos_name": name,
    })

_BY_ID = {r["id"]: r for r in CATALOG}


def _build_args(report_id: str, body: dict) -> tuple[str, str, list[str]]:
    meta = _BY_ID.get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Reporte desconocido")
    platform = body.get("platform") or meta["platform"]
    if meta["platform"] != "both":
        platform = require_platform(str(platform))
    fmt = str(body.get("format") or "json").lower()
    if fmt not in meta["formats"]:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: {fmt}")
    args: list[str] = ["--json" if fmt == "json" else "--csv"]
    params = meta.get("params") or []
    for key in ("start", "end"):
        if key in params and body.get(key):
            value = str(body[key])
            if not DATE_RE.match(value):
                raise HTTPException(status_code=400, detail=f"{key} debe ser AAAA-MM-DD")
            args += [f"--{key}", value]
    if "store" in params and body.get("store"):
        args += ["--store", str(body["store"])[:120]]
    for sid in body.get("store_ids") or []:
        args += ["--id", str(sid)[:80]]
    if report_id == "uber_disputes" and body.get("status"):
        if body["status"] not in ("pending", "charged", "disputed", "accepted", "rejected"):
            raise HTTPException(status_code=400, detail="status inválido")
        args += ["--status", str(body["status"])]
    if report_id == "uber_hours":
        try:
            days = max(1, min(int(body.get("days") or 30), 90))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="days debe ser un entero") from exc
        args += ["--days", str(days)]
    if report_id == "pya_issues" and body.get("by_store"):
        args.append("--by-store")
    cmd = {
        "stores_snapshot": None,
        "uber_disputes": "disputes",
        "uber_sales": "sales",
        "uber_soldout": "soldout-report",
        "uber_hours": "hours",
        "pya_sales": "sales",
        "pya_soldout": "soldout-report",
        "pya_reviews": "reviews",
        "pya_ratings": "ratings",
        "pya_issues": "issues",
        "pya_orders": "orders",
        "pya_payouts": "payouts",
        "pya_earnings": "earnings",
        "pya_invoices": "invoices",
    }.get(report_id)
    if report_id.startswith("pya_vos_"):
        cmd = "report"
        vos = meta.get("vos_name") or body.get("vos_name")
        if not vos:
            raise HTTPException(status_code=400, detail="Falta vos_name")
        args = [vos, *args]
    if report_id == "stores_snapshot":
        return "snapshot", platform, []
    if not cmd:
        raise HTTPException(status_code=501, detail="Reporte aún no cableado")
    return cmd, platform, args


def _run_report(report_id: str, body: dict, user: str) -> dict:
    settings = get_settings()
    cmd, platform, args = _build_args(report_id, body)
    fmt = str(body.get("format") or "json").lower()
    job = jobs.create_job(f"report:{report_id}", user, dry_run=False, input_sanitized={
        "report": report_id, "platform": platform, "format": fmt,
    })
    jobs.update_job(job["id"], status="running")
    try:
        if cmd == "snapshot":
            from ..main import public_snapshot

            try:
                snap = json.loads(settings.snapshot_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=409, detail="Sin snapshot: actualícelo desde Monitoreo") from exc
            stores = public_snapshot(snap).get("stores") or []
            payload = json.dumps(stores, ensure_ascii=False, indent=1).encode("utf-8")
            path = jobs.save_artifact(job["id"], "stores_snapshot.json", payload)
            jobs.update_job(job["id"], status="done", artifact_path=str(path), result_summary=f"{len(stores)} tiendas")
            return jobs.public_job(jobs.get_job(job["id"]) or job)
        require_session(settings, platform)
        script, cwd = script_paths(settings, platform)
        if fmt == "json":
            out = run_json_cli(script, [cmd, *args], cwd, REPORT_TIMEOUT)
            payload = json.dumps(out.data, ensure_ascii=False).encode("utf-8")
            path = jobs.save_artifact(job["id"], f"{report_id}.json", payload)
            summary = f"{len(out.data) if isinstance(out.data, list) else 1} filas"
        else:
            proc = run_cli(script, [cmd, *args], cwd, REPORT_TIMEOUT)
            if proc.returncode != 0:
                raise CliError(sanitize(proc.stderr or proc.stdout) or "CLI falló", proc.returncode)
            payload = (proc.stdout or "").encode("utf-8")
            path = jobs.save_artifact(job["id"], f"{report_id}.csv", payload)
            summary = f"{max(0, len(payload.splitlines()) - 1)} filas CSV"
        jobs.update_job(job["id"], status="done", artifact_path=str(path), result_summary=summary)
    except (CliError, HTTPException) as exc:
        msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
        jobs.update_job(job["id"], status="error", error=str(msg))
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
    return jobs.public_job(jobs.get_job(job["id"]) or job)


@router.get("")
async def list_reports(request: Request):
    operator(request)
    return {"reports": CATALOG, "timezone": "America/Santiago"}


@router.post("/run")
async def run_report(request: Request, body: dict = Body(...)):
    user = operator(request)
    report_id = str(body.get("report") or "")
    audit(user, "reports.run", report_id, False, "inicio")
    result = await asyncio.to_thread(_run_report, report_id, body or {}, user)
    audit(user, "reports.run", report_id, False, result.get("status") or "ok")
    return result


@router.get("/jobs/{job_id}")
async def job_status(request: Request, job_id: str):
    operator(request)
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return jobs.public_job(job)


@router.get("/jobs/{job_id}/download")
async def job_download(request: Request, job_id: str):
    operator(request)
    job = jobs.get_job(job_id)
    if not job or not job.get("artifact_path"):
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    path = Path(job["artifact_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path, filename=path.name, headers={"Cache-Control": "private, no-store"})
