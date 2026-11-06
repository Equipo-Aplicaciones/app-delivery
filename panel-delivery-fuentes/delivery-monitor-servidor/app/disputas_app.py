"""Panel exclusivo de disputas y credenciales.

Arranque: `PANEL_AUTH=false uvicorn app.disputas_app:app` para dejarlo sin inicio de sesión.
Sin esa variable usa el mismo login y cookie que el panel completo.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from delivery_monitor.sanitize import sanitize

from .auth import (
    allow_login_attempt,
    clear_session,
    current_user,
    forget_login_attempts,
    issue_session,
    verify_credentials,
)
from .config import SettingsError
from .deps import get_settings
from .modules import credentials as credentials_module
from .modules import disputas_panel
from .modules import disputes as disputes_module

log = logging.getLogger("delivery_monitor.disputas")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
    except SettingsError as exc:
        log.error("configuración inválida: %s", exc)
        raise SystemExit(str(exc)) from exc
    for folder in (settings.media_dir, settings.sessions_dir, settings.data_dir):
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            log.warning("no se pudo crear %s: %s", folder, exc.strerror)
    credentials_module.ensure_links(settings)
    if not settings.auth_required:
        log.warning("panel de disputas SIN inicio de sesión (PANEL_AUTH=false): no lo exponga sin otra protección")
    yield


app = FastAPI(title="Disputas delivery", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(credentials_module.router)
app.include_router(disputes_module.router)
app.include_router(disputas_panel.router)


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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon():
    return HTMLResponse("", status_code=204)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = get_settings()
    if settings.auth_required and not current_user(request, settings):
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse((STATIC_DIR / "disputas.html").read_text(encoding="utf-8"))


def _login_page(error: str | None = None) -> str:
    html = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    return html.replace("<!--ERROR-->", f'<p class="error">{error}</p>' if error else "")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    settings = get_settings()
    if not settings.auth_required or current_user(request, settings):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(_login_page())


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = get_settings()
    if not settings.auth_required:
        return RedirectResponse("/", status_code=303)
    ip = request.client.host if request.client else "unknown"
    if not allow_login_attempt(ip):
        return HTMLResponse(_login_page("Demasiados intentos. Espere unos minutos."), status_code=429)
    if not verify_credentials(settings, username, password):
        return HTMLResponse(_login_page("Usuario o contraseña incorrectos."), status_code=401)
    forget_login_attempts(ip)
    response = RedirectResponse("/", status_code=303)
    issue_session(response, settings, settings.panel_user)
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    clear_session(response, get_settings())
    return response
