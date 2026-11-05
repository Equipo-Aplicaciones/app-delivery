"""API y panel web. Solo lectura hacia las plataformas."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from delivery_monitor.classify import STATUS_LABELS
from delivery_monitor.refresh import refresh as run_refresh
from delivery_monitor.sanitize import sanitize
from delivery_monitor.adapters.rappi import PENDING_NOTE

from .auth import (
    allow_login_attempt,
    clear_session,
    current_user,
    issue_session,
    require_user,
    verify_credentials,
)
from .config import SettingsError
from .deps import get_settings
from .modules import credentials as credentials_module
from .modules import disputes as disputes_module

log = logging.getLogger("delivery_monitor.panel")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC_DIR = Path(__file__).resolve().parent / "static"
COVERAGE = {
    "timezone": "America/Santiago",
    "rappi": PENDING_NOTE,
    "pedidosya_disputas": (
        "PedidosYa no tiene un listado de disputas equivalente al de Uber. "
        "Los mosaicos de `issues` son reclamos o descuentos: un reclamo no se cuenta "
        "como disputa pendiente. Solo se confirmaría con `order` pedido a pedido, "
        "cosa que este panel no hace."
    ),
    "uber_disputas": (
        "En Uber, una disputa sin abrir es un cobro pendiente "
        "(`disputes --status pending`) que el local aún no discutió. "
        "La elegibilidad comprobada solo aparece si vino en el JSON."
    ),
    "sesiones": (
        "Las sesiones de Uber (~/.uber_cookie) y PedidosYa (~/.pya_tokens.json) "
        "las provee el dueño montándolas en /sessions. No se renuevan solas desde "
        "un navegador; si caducan hay que volver a copiar los archivos. "
        "PedidosYa puede refrescar el access token con su propio refresh_token "
        "si el archivo es escribible; eso no migra la rutina local del navegador."
    ),
    "snapshot": (
        "Este panel no consulta las plataformas al cargar. Usa el último snapshot "
        "o un refresh autenticado. Un refresh no escribe en las plataformas."
    ),
}

_refresh_lock = threading.Lock()
_refresh_running = False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return request.client.host if request.client else "unknown"


def _public_store(row: dict) -> dict:
    return {
        "platform": row.get("platform"),
        "store_id": row.get("store_id"),
        "name": row.get("name"),
        "brand": row.get("brand"),
        "status": row.get("status"),
        "status_raw": row.get("status_raw"),
        "open_now": row.get("open_now"),
        "enabled": row.get("enabled"),
        "reason": row.get("reason"),
        "since": row.get("since"),
        "until": row.get("until"),
        "next_open": row.get("next_open"),
        "next_close": row.get("next_close"),
        "slot": row.get("slot"),
        "excluded": row.get("excluded"),
    }


def _public_dispute(row: dict) -> dict:
    return {
        "platform": row.get("platform"),
        "store_name": row.get("store_name"),
        "brand": row.get("brand"),
        "order_id": row.get("order_id"),
        "ordered_at": row.get("ordered_at"),
        "amount_clp": row.get("amount_clp"),
        "amount_display": row.get("amount_display"),
        "issue": row.get("issue"),
        "tag": row.get("tag"),
        "state": row.get("state"),
        "eligibility": row.get("eligibility"),
        "window_start": row.get("window_start"),
        "window_end": row.get("window_end"),
    }


def _pending_source(name: str, error: str) -> dict:
    return {
        "status": "pending",
        "fetched_at": None,
        "error": error,
        "stores_count": None,
        "disputes_status": "pending" if name != "pedidosya" else "no_direct_list",
        "disputes_error": error if name != "pedidosya" else COVERAGE["pedidosya_disputas"],
        "disputes_count": None,
        "disputes_window": None,
    }


def empty_payload(message: str, *, source_error: str | None = None) -> dict:
    err = source_error or message
    sources = {
        "uber": _pending_source("uber", err),
        "pedidosya": _pending_source("pedidosya", err),
        "rappi": _pending_source("rappi", PENDING_NOTE),
    }
    return {
        "available": False,
        "generated_at": None,
        "timezone": "America/Santiago",
        "message": message,
        "sources": sources,
        "totals": None,
        "stores": [],
        "disputes": [],
        "complaint_tiles": [],
        "coverage": COVERAGE,
        "status_labels": STATUS_LABELS,
        "integration": None,
    }


def public_snapshot(snap: dict) -> dict:
    sources = {}
    for name, src in (snap.get("sources") or {}).items():
        if not isinstance(src, dict):
            continue
        sources[name] = {
            "status": src.get("status"),
            "fetched_at": src.get("fetched_at"),
            "error": sanitize(src.get("error")),
            "stores_count": src.get("stores_count"),
            "disputes_status": src.get("disputes_status"),
            "disputes_error": sanitize(src.get("disputes_error")),
            "disputes_count": src.get("disputes_count"),
            "disputes_window": src.get("disputes_window"),
            "disputes_truncated": src.get("disputes_truncated"),
        }
    tiles = []
    for tile in snap.get("complaint_tiles") or []:
        if not isinstance(tile, dict):
            continue
        tiles.append({
            "store": tile.get("store"),
            "type": tile.get("type"),
            "orders": tile.get("orders"),
            "amount": tile.get("amount"),
            "amount_type": tile.get("amount_type"),
            "orders_with_amount": tile.get("orders_with_amount"),
            "window_start": tile.get("window_start"),
            "window_end": tile.get("window_end"),
            "note": tile.get("note") or "reclamo agregado; no es una disputa pendiente confirmada",
        })
    return {
        "available": True,
        "generated_at": snap.get("generated_at"),
        "timezone": snap.get("timezone") or "America/Santiago",
        "message": None,
        "sources": sources,
        "totals": snap.get("totals"),
        "stores": [_public_store(s) for s in (snap.get("stores") or []) if isinstance(s, dict)],
        "disputes": [_public_dispute(d) for d in (snap.get("disputes") or []) if isinstance(d, dict)],
        "complaint_tiles": tiles,
        "coverage": COVERAGE,
        "status_labels": snap.get("status_labels") or STATUS_LABELS,
        "integration": snap.get("integration"),
    }


def load_payload() -> dict:
    path = get_settings().snapshot_path
    if not path.is_file():
        return empty_payload(
            "Aún no hay snapshot. Configure las sesiones de Uber y PedidosYa "
            "y ejecute un refresh autenticado."
        )
    try:
        raw = path.read_text(encoding="utf-8")
        snap = json.loads(raw)
    except Exception:
        log.warning("snapshot ilegible en %s", path)
        return empty_payload(
            "Hay un archivo de snapshot pero no se pudo leer. No se muestran cifras.",
            source_error="snapshot ilegible",
        )
    if not isinstance(snap, dict):
        return empty_payload("El snapshot no tiene el formato esperado.", source_error="snapshot inválido")
    return public_snapshot(snap)


def _do_refresh() -> dict:
    settings = get_settings()
    settings.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snap = run_refresh(settings.snapshot_path)
    return public_snapshot(snap)


async def _interval_loop(stop: asyncio.Event, minutes: int) -> None:
    delay = minutes * 60
    log.info("intervalo de refresh habilitado: cada %s min (no corre al arrancar)", minutes)
    try:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.to_thread(_locked_refresh)
            except Exception as exc:
                log.error("refresh programado falló: %s", sanitize(str(exc)))
    except asyncio.CancelledError:
        return


def _locked_refresh() -> dict:
    global _refresh_running
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ya hay un refresh en curso")
    try:
        _refresh_running = True
        return _do_refresh()
    finally:
        _refresh_running = False
        _refresh_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
    except SettingsError as exc:
        log.error("configuración inválida: %s", exc)
        raise SystemExit(str(exc)) from exc
    for folder in (settings.media_dir, settings.sessions_dir):
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            log.warning("no se pudo crear %s: %s", folder, exc.strerror)
    credentials_module.ensure_links(settings)
    log.info("panel listo (snapshot=%s, intervalo=%s)", settings.snapshot_path, settings.refresh_interval_minutes)
    stop = asyncio.Event()
    task = None
    if settings.refresh_interval_minutes >= 15:
        task = asyncio.create_task(_interval_loop(stop, settings.refresh_interval_minutes))
    yield
    stop.set()
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="Monitoreo de delivery", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(credentials_module.router)
app.include_router(disputes_module.router)


@app.exception_handler(SettingsError)
async def _settings_error(_, exc: SettingsError):
    return JSONResponse({"detail": "Servicio no configurado"}, status_code=503)


@app.exception_handler(StarletteHTTPException)
async def _http_exc(request: Request, exc: StarletteHTTPException):
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        return await http_exception_handler(request, exc)
    log.error("error interno: %s", sanitize(str(exc)))
    return JSONResponse({"detail": "Error interno"}, status_code=500)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except SettingsError:
        return JSONResponse({"detail": "Servicio no configurado"}, status_code=503)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _login_page(error: str | None = None) -> str:
    html = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    notice = f'<p class="error">{error}</p>' if error else ""
    return html.replace("<!--ERROR-->", notice)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    settings = get_settings()
    if current_user(request, settings):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_login_page())


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = get_settings()
    ip = _client_ip(request)
    if not allow_login_attempt(ip):
        return HTMLResponse(_login_page("Demasiados intentos. Espere unos minutos."), status_code=429)
    if not verify_credentials(settings, username, password):
        return HTMLResponse(_login_page("Usuario o contraseña incorrectos."), status_code=401)
    response = RedirectResponse("/", status_code=303)
    issue_session(response, settings, settings.panel_user)
    return response


@app.post("/api/login")
def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = get_settings()
    ip = _client_ip(request)
    if not allow_login_attempt(ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos")
    if not verify_credentials(settings, username, password):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    response = JSONResponse({"ok": True})
    issue_session(response, settings, settings.panel_user)
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    clear_session(response, get_settings())
    return response


@app.post("/api/logout")
def api_logout():
    response = JSONResponse({"ok": True})
    clear_session(response, get_settings())
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = get_settings()
    if not current_user(request, settings):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/snapshot")
def api_snapshot(request: Request):
    require_user(request, get_settings())
    return load_payload()


@app.get("/api/health")
def api_health(request: Request):
    require_user(request, get_settings())
    payload = load_payload()
    return {
        "status": "ok" if payload.get("available") else "pending",
        "available": payload.get("available"),
        "generated_at": payload.get("generated_at"),
        "sources": payload.get("sources"),
        "refresh_running": _refresh_running,
        "coverage": COVERAGE,
    }


@app.post("/api/refresh")
async def api_refresh(request: Request):
    require_user(request, get_settings())
    settings = get_settings()
    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(_locked_refresh),
            timeout=settings.refresh_timeout,
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="El refresh superó el tiempo máximo")
    except Exception as exc:
        log.error("refresh falló: %s", sanitize(str(exc)))
        raise HTTPException(status_code=502, detail=sanitize(str(exc)) or "El refresh no se pudo completar")
    return payload
