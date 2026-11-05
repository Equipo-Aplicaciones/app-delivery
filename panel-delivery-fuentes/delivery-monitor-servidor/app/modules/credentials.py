"""Reposición de sesiones de plataforma. El valor nunca vuelve en una respuesta ni en logs."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from delivery_monitor.adapters.runner import CliError, run_cli
from delivery_monitor.parseutil import iso_chile
from delivery_monitor.sanitize import looks_like_auth_failure, sanitize

from ..config import Settings
from ..deps import audit, get_settings, operator
from . import evidence

log = logging.getLogger("delivery_monitor.credentials")
router = APIRouter(prefix="/api/credentials")

SOURCES = {
    "uber": {"file": "uber_cookie", "home_name": ".uber_cookie", "label": "Uber"},
    "pedidosya": {"file": "pya_tokens.json", "home_name": ".pya_tokens.json", "label": "PedidosYa"},
}
MAX_VALUE = 64 * 1024
PROBE_TIMEOUT = int(os.environ.get("CREDENTIALS_PROBE_TIMEOUT", "90"))
CACHE_TTL = 600.0
OTP_HINT = (
    "El access token y el refresh de PedidosYa caducaron: hace falta login OTP en el portal "
    "y pegar un pya_tokens.json nuevo."
)
RAPPI_NOTE = "Rappi pendiente: no hay CLI ni client_id/client_secret. No se aceptan tokens sin health check."

_PROBE_CODE = {
    "uber": (
        "import json\nfrom api_client import UberEatsClient\n"
        "print(json.dumps({'stores': len(UberEatsClient().list_stores())}))"
    ),
    "pedidosya": (
        "import json\nfrom api_client import PedidosYaClient\n"
        "print(json.dumps({'stores': len(PedidosYaClient().list_stores())}))"
    ),
}

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_write_lock = threading.Lock()


def session_file(settings: Settings, source: str) -> Path:
    return settings.sessions_dir / SOURCES[source]["file"]


def has_session(settings: Settings, source: str) -> bool:
    if session_file(settings, source).is_file():
        return True
    if (settings.cli_home / SOURCES[source]["home_name"]).is_file():
        return True
    return source == "uber" and bool((os.environ.get("UBER_COOKIE") or "").strip())


def ensure_links(settings: Settings) -> None:
    """Hace que ~/.uber_cookie y ~/.pya_tokens.json del CLI apunten a /sessions."""
    for meta in SOURCES.values():
        target = settings.sessions_dir / meta["file"]
        link = settings.cli_home / meta["home_name"]
        try:
            if link.resolve() == target.resolve():
                continue
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                log.warning("%s existe como archivo propio; no se reemplaza por el enlace a sesiones", link)
                continue
            settings.cli_home.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
        except OSError as exc:
            log.warning("no se pudo enlazar %s: %s", link.name, exc.strerror)


def _cli_cwd(settings: Settings, source: str) -> str:
    return settings.uber_cli_cwd if source == "uber" else settings.pya_cli_cwd


def probe(settings: Settings, source: str, home: str | None = None) -> tuple[str, str]:
    """Lectura mínima (lista de tiendas). Devuelve (estado, detalle) sin secretos."""
    try:
        proc = run_cli("-c", [_PROBE_CODE[source]], _cli_cwd(settings, source), PROBE_TIMEOUT,
                       home=home or str(settings.cli_home))
    except CliError as exc:
        return "unknown", sanitize(str(exc))
    out = (proc.stdout or "").strip()
    err = proc.stderr or ""
    if proc.returncode == 0:
        try:
            n = int(json.loads(out.splitlines()[-1]).get("stores"))
            return "configured", f"Sesión válida: {n} tiendas visibles"
        except (ValueError, IndexError, AttributeError, TypeError):
            return "unknown", "El chequeo no devolvió el formato esperado"
    combined = out + "\n" + err
    if source == "pedidosya" and any(m in combined for m in ("PYA_USER", "OTP_REQUIRED", "Login failed")):
        return "expired", OTP_HINT
    if looks_like_auth_failure(combined) or "No Uber cookie" in combined:
        return "expired", f"{SOURCES[source]['label']} rechazó la sesión (401/403 o caducada)"
    last = [line for line in err.strip().splitlines() if line.strip()]
    return "unknown", sanitize(last[-1] if last else f"exit {proc.returncode}", 200)


def _store_status(source: str, status: str, detail: str) -> dict:
    entry = {"status": status, "checked_at": iso_chile(), "detail": detail, "_mono": time.monotonic()}
    with _cache_lock:
        _cache[source] = entry
    return entry


def _public(source: str, entry: dict, configured_file: bool) -> dict:
    return {
        "source": source,
        "label": SOURCES[source]["label"] if source in SOURCES else source.capitalize(),
        "status": entry.get("status"),
        "checked_at": entry.get("checked_at"),
        "detail": entry.get("detail"),
        "file_present": configured_file,
    }


def status_for(settings: Settings, source: str, force: bool = False) -> dict:
    if not has_session(settings, source):
        entry = _store_status(source, "missing", "No hay sesión cargada")
        return _public(source, entry, False)
    with _cache_lock:
        cached = _cache.get(source)
    if cached and not force and cached["status"] != "missing" and time.monotonic() - cached["_mono"] < CACHE_TTL:
        return _public(source, cached, True)
    status, detail = probe(settings, source)
    return _public(source, _store_status(source, status, detail), True)


def _evidence_status(settings: Settings, force: bool) -> dict:
    with _cache_lock:
        cached = _cache.get("evidencia")
    if not settings.evidencia_api_key:
        entry = _store_status("evidencia", "missing", "Falta EVIDENCIA_API_KEY en el servidor (se configura por entorno, no desde el panel)")
    elif cached and not force and cached["status"] != "missing" and time.monotonic() - cached["_mono"] < CACHE_TTL:
        entry = cached
    else:
        entry = _store_status("evidencia", *evidence.health(settings))
    return {
        "source": "evidencia",
        "label": "App delivery (evidencia)",
        "status": entry["status"],
        "checked_at": entry["checked_at"],
        "detail": entry["detail"],
        "file_present": bool(settings.evidencia_api_key),
    }


@router.get("/status")
async def credentials_status(request: Request, check: bool = False):
    operator(request)
    settings = get_settings()
    uber, pya, evid = await asyncio.gather(
        asyncio.to_thread(status_for, settings, "uber", check),
        asyncio.to_thread(status_for, settings, "pedidosya", check),
        asyncio.to_thread(_evidence_status, settings, check),
    )
    rappi = {"source": "rappi", "label": "Rappi", "status": "pending", "checked_at": None,
             "detail": RAPPI_NOTE, "file_present": False}
    return {"sources": [uber, pya, rappi, evid], "timezone": "America/Santiago"}


async def _read_value(value: str | None, file: UploadFile | None) -> str:
    raw = b""
    if file is not None and file.filename:
        raw = await file.read(MAX_VALUE + 1)
    elif value:
        raw = value.encode("utf-8")
    if not raw:
        raise HTTPException(status_code=400, detail="Falta el valor o el archivo")
    if len(raw) > MAX_VALUE:
        raise HTTPException(status_code=413, detail="El valor supera 64 KB")
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="El archivo no es texto UTF-8") from exc


def _normalize(source: str, text: str) -> str:
    if source == "uber":
        if text.lower().startswith("cookie:"):
            text = text.split(":", 1)[1].strip()
        if "=" not in text or "\n" in text:
            raise HTTPException(status_code=400, detail="La cookie debe ser el header Cookie en una sola línea (pares nombre=valor)")
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="pya_tokens.json no es JSON válido") from exc
    if not isinstance(data, dict) or not (data.get("access") or data.get("refresh")):
        raise HTTPException(status_code=400, detail="pya_tokens.json debe traer las claves access y/o refresh")
    return json.dumps({k: data.get(k) for k in ("access", "refresh", "device") if k in data})


def _write_private(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


def _replace_session(settings: Settings, source: str, candidate: Path) -> None:
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    final = session_file(settings, source)
    tmp = final.with_name(final.name + ".tmp")
    shutil.copyfile(candidate, tmp)
    os.chmod(tmp, 0o600)
    if final.is_file():
        bak = final.with_name(final.name + ".bak")
        shutil.copyfile(final, bak)
        os.chmod(bak, 0o600)
    os.replace(tmp, final)
    ensure_links(settings)


def install(settings: Settings, source: str, content: str) -> tuple[str, str]:
    """Prueba la credencial en un HOME aislado; solo reemplaza la vigente si el chequeo pasa."""
    with _write_lock:
        home = tempfile.mkdtemp(prefix="cred-probe-")
        try:
            os.chmod(home, 0o700)
            candidate = Path(home) / SOURCES[source]["home_name"]
            _write_private(candidate, content)
            status, detail = probe(settings, source, home=home)
            if status == "configured":
                _replace_session(settings, source, candidate)
                _store_status(source, status, detail)
            return status, detail
        finally:
            shutil.rmtree(home, ignore_errors=True)


def _length_hint(n: int) -> str:
    for limit in (256, 1024, 4096, 16384):
        if n <= limit:
            return f"≤{limit} caracteres"
    return ">16384 caracteres"


async def _put(request: Request, source: str, value: str | None, file: UploadFile | None):
    user = operator(request)
    settings = get_settings()
    content = _normalize(source, await _read_value(value, file))
    status, detail = await asyncio.to_thread(install, settings, source, content)
    ok = status == "configured"
    audit(user, f"credentials.put.{source}", source, False, "ok" if ok else status, detail)
    body = {
        "ok": ok,
        "source": source,
        "status": status,
        "checked_at": iso_chile(),
        "detail": detail if ok else f"No se guardó: {detail}. La sesión anterior quedó intacta.",
        "length": _length_hint(len(content)),
    }
    if not ok:
        raise HTTPException(status_code=422, detail=body["detail"])
    return body


@router.put("/uber")
async def put_uber(request: Request, value: str | None = Form(None), file: UploadFile | None = File(None)):
    return await _put(request, "uber", value, file)


@router.put("/pedidosya")
async def put_pedidosya(request: Request, value: str | None = Form(None), file: UploadFile | None = File(None)):
    return await _put(request, "pedidosya", value, file)


@router.put("/rappi")
async def put_rappi(request: Request):
    operator(request)
    raise HTTPException(status_code=501, detail=RAPPI_NOTE)


@router.delete("/{source}")
async def delete_session(request: Request, source: str, confirm: bool = False):
    user = operator(request)
    settings = get_settings()
    if source == "rappi":
        raise HTTPException(status_code=501, detail=RAPPI_NOTE)
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail="Fuente desconocida")
    path = session_file(settings, source)
    exists = path.is_file()
    if not confirm:
        audit(user, f"credentials.delete.{source}", source, True, "dry-run")
        return {"dry_run": True, "results": [{"source": source, "would_delete": exists}], "verified": None}
    removed = False
    with _write_lock:
        for p in (path, path.with_name(path.name + ".bak")):
            if p.is_file():
                p.unlink()
                removed = True
    _store_status(source, "missing", "Sesión borrada desde el panel")
    audit(user, f"credentials.delete.{source}", source, False, "ok" if removed else "nada que borrar")
    return {"dry_run": False, "results": [{"source": source, "deleted": removed}], "verified": not session_file(settings, source).exists()}
