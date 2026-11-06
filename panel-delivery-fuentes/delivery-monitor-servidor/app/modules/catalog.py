"""Catálogo: informe de agotados, agotar/reponer ítems y activate-menu (dry-run por defecto)."""
from __future__ import annotations

import asyncio
import os
import re

from fastapi import APIRouter, Body, HTTPException, Request

from ..deps import audit, get_settings, operator
from .cli_helpers import require_platform, require_session, run_tolerant, store_args, write_flags

router = APIRouter(prefix="/api/catalog")

WRITE_TIMEOUT = int(os.environ.get("CATALOG_WRITE_TIMEOUT", "900"))
READ_TIMEOUT = int(os.environ.get("CATALOG_READ_TIMEOUT", "600"))
PYA_UNTIL_RE = re.compile(r"^(indefinite|tomorrow|\d{1,4})$")


def _stores_or_all(body: dict) -> list[str]:
    if body.get("store_ids") or body.get("names"):
        return store_args(body)
    return ["--json"]


@router.get("/soldout")
async def soldout_report(request: Request, platform: str = "uber", store: str | None = None):
    operator(request)
    platform = require_platform(platform)
    settings = get_settings()
    require_session(settings, platform)
    args = ["soldout-report", "--json"] + (["--store", store] if store else [])
    result = await asyncio.to_thread(run_tolerant, settings, platform, args, READ_TIMEOUT, confirm=False)
    rows = result["results"] if isinstance(result["results"], list) else []
    return {"platform": platform, "items": rows, "count": len(rows), "log": result.get("log")}


def _item_write(user: str, mode: str, body: dict) -> dict:
    settings = get_settings()
    platform = require_platform(str(body.get("platform") or ""))
    item = str(body.get("item") or "").strip()
    if not item:
        raise HTTPException(status_code=400, detail="Falta el producto (item)")
    confirm = body.get("confirm") is True
    args = [mode, *_stores_or_all(body), *write_flags(confirm), "--item", item[:200]]
    if body.get("match") == "contains":
        args.append("--contains")
    if mode == "soldout":
        if platform == "uber":
            until = str(body.get("until") or "today")
            if until not in ("today", "indefinite"):
                raise HTTPException(status_code=400, detail="Uber: until debe ser today o indefinite")
        else:
            until = str(body.get("until") or "indefinite")
            if not PYA_UNTIL_RE.match(until):
                raise HTTPException(status_code=400, detail="PedidosYa: until debe ser indefinite, tomorrow o minutos")
        args += ["--until", until]
    require_session(settings, platform)
    try:
        result = run_tolerant(settings, platform, args, WRITE_TIMEOUT, confirm=confirm)
    except HTTPException as exc:
        audit(user, f"catalog.{mode}", f"{platform}:{item[:60]}", not confirm, "error", str(exc.detail))
        raise
    audit(user, f"catalog.{mode}", f"{platform}:{item[:60]}", not confirm, "ok" if confirm else "dry-run")
    return {**result, "platform": platform, "action": mode}


@router.post("/soldout")
async def mark_soldout(request: Request, body: dict = Body(...)):
    user = operator(request)
    return await asyncio.to_thread(_item_write, user, "soldout", body or {})


@router.post("/instock")
async def mark_instock(request: Request, body: dict = Body(...)):
    user = operator(request)
    return await asyncio.to_thread(_item_write, user, "instock", body or {})


def _activate_menu(user: str, body: dict) -> dict:
    settings = get_settings()
    platform = require_platform(str(body.get("platform") or ""))
    confirm = body.get("confirm") is True
    args = ["activate-menu", *_stores_or_all(body), *write_flags(confirm)]
    if "--json" not in args:
        args.append("--json")
    for ex in body.get("extra_excludes") or []:
        if str(ex).strip():
            args += ["--exclude", str(ex).strip()[:200]]
    require_session(settings, platform)
    try:
        result = run_tolerant(settings, platform, args, WRITE_TIMEOUT, confirm=confirm)
    except HTTPException as exc:
        audit(user, "catalog.activate_menu", platform, not confirm, "error", str(exc.detail))
        raise
    rows = result["results"] if isinstance(result["results"], list) else []
    audit(user, "catalog.activate_menu", platform, not confirm, "ok" if confirm else "dry-run", f"filas={len(rows)}")
    return {**result, "platform": platform, "action": "activate-menu"}


@router.post("/activate-menu")
async def activate_menu(request: Request, body: dict = Body(...)):
    user = operator(request)
    return await asyncio.to_thread(_activate_menu, user, body or {})
