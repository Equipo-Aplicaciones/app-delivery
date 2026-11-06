"""Configuración compartida, sesión requerida y auditoría de acciones."""
from __future__ import annotations

import json
import os
import threading

from fastapi import Request

from delivery_monitor.parseutil import iso_chile
from delivery_monitor.sanitize import sanitize

from .auth import require_user
from .config import Settings, load_settings

_settings: Settings | None = None
_audit_lock = threading.Lock()


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None


_SCOPE_RULES: tuple[tuple[str, str, str | None], ...] = (
    ("/api/agents", "*", None),
    ("/api/credentials", "*", None),
    ("/api/media/", "PATCH", "disputes.write"),
    ("/api/disputes/", "POST", "disputes.write"),
    ("/api/disputes", "GET", "disputes.read"),
    ("/api/orders/", "GET", "disputes.read"),
    ("/api/evidence/", "GET", "disputes.read"),
    ("/api/stores", "GET", "snapshot.read"),
    ("/api/stores", "POST", "stores.write"),
    ("/api/catalog", "GET", "reports.read"),
    ("/api/catalog", "POST", "catalog.write"),
    ("/api/reports", "*", "reports.read"),
    ("/api/automations", "*", "automations.write"),
    ("/api/snapshot", "GET", "snapshot.read"),
    ("/api/health", "GET", "snapshot.read"),
    ("/api/refresh", "POST", "snapshot.read"),
)


def required_scope(request: Request) -> str | None:
    """Scope que necesita un agente para esta ruta. None = solo operador humano."""
    path, method = request.url.path, request.method.upper()
    for prefix, rule_method, scope in _SCOPE_RULES:
        if path.startswith(prefix) and rule_method in ("*", method):
            return scope
    return None


def operator(request: Request) -> str:
    """Operador por cookie de sesión o agente por `Authorization: Bearer tdk_…` con el scope de la ruta."""
    if not get_settings().auth_required:
        return "sin-login"
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer ") and not request.cookies.get("dm_session"):
        from .modules import agents

        return agents.authenticate(auth[7:].strip(), required_scope(request))
    return require_user(request, get_settings())


def audit(actor: str, action: str, target: str, dry_run: bool, result: str, detail: str = "") -> None:
    """Una línea JSON por intento de escritura. Nunca recibe secretos; igual se sanitiza."""
    settings = get_settings()
    entry = {
        "at": iso_chile(),
        "actor": actor,
        "action": action,
        "target": sanitize(target, 200),
        "dry_run": dry_run,
        "result": sanitize(result, 200),
        "detail": sanitize(detail, 400),
    }
    path = settings.audit_path
    with _audit_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
