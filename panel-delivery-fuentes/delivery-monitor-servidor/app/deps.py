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


def operator(request: Request) -> str:
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
