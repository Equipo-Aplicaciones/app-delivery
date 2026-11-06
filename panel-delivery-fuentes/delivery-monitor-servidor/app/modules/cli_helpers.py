"""Argumentos comunes para invocar uber.py / pya.py desde el panel."""
from __future__ import annotations

import json
import threading

from fastapi import HTTPException

from delivery_monitor.adapters.runner import CliError, run_cli
from delivery_monitor.sanitize import looks_like_auth_failure, sanitize

from ..config import Settings
from .credentials import has_session

_write_slots = threading.BoundedSemaphore(1)


def run_tolerant(settings: Settings, platform: str, args: list[str], timeout: int, *, confirm: bool) -> dict:
    """Corre un comando del CLI y devuelve JSON si lo hay o el texto saneado (pya imprime texto en escrituras)."""
    script, cwd = script_paths(settings, platform)
    try:
        with _write_slots:
            proc = run_cli(script, args, cwd, timeout)
    except CliError as exc:
        raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    if proc.returncode != 0:
        auth = looks_like_auth_failure(stdout + stderr)
        tail = (stderr.strip().splitlines() or stdout.strip().splitlines() or [f"exit {proc.returncode}"])[-1]
        raise HTTPException(status_code=502, detail=("Sesión rechazada por la plataforma. " if auth else "") + sanitize(tail, 400))
    results = None
    text = stdout.strip()
    if text and text[0] in "[{":
        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            results = None
    if text.startswith("(sin resultados)"):
        results = []
    return {
        "dry_run": not confirm,
        "verified": False,
        "results": results,
        "output": None if results is not None else sanitize(text, 6000),
        "log": sanitize("\n".join(stderr.strip().splitlines()[-8:]), 1500) or None,
    }


def require_platform(platform: str) -> str:
    if platform not in ("uber", "pedidosya"):
        raise HTTPException(status_code=400, detail="platform debe ser uber o pedidosya")
    return platform


def require_session(settings: Settings, platform: str) -> None:
    if not has_session(settings, platform):
        label = "Uber" if platform == "uber" else "PedidosYa"
        raise HTTPException(status_code=409, detail=f"Sin sesión de {label}: cárguela en Credenciales")


def store_args(body: dict) -> list[str]:
    ids = [str(x) for x in body.get("store_ids") or [] if str(x).strip()]
    names = [str(x) for x in (body.get("names") or body.get("store_names") or []) if str(x).strip()]
    if not ids and not names:
        raise HTTPException(status_code=400, detail="Indique store_ids o names")
    args = ["--json"]
    for i in ids:
        args += ["--id", i]
    for n in names:
        args += ["--store", n]
    return args


def write_flags(confirm: bool) -> list[str]:
    return ["--yes"] if confirm is True else ["--dry-run"]


def script_paths(settings: Settings, platform: str) -> tuple[str, str]:
    if platform == "uber":
        return settings.uber_cli, settings.uber_cli_cwd
    return settings.pya_cli, settings.pya_cli_cwd
