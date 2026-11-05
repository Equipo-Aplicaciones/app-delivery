"""Configuración por entorno. Sin contraseñas por defecto."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WEAK_PASSWORDS = frozenset({
    "", "password", "admin", "changeme", "secret", "123456", "12345678",
    "panel", "tarragona", "passw0rd", "cambiar-esta-clave",
    "cambiar-por-al-menos-32-caracteres-aleatorios",
})

WEAK_SECRETS = frozenset({
    "", "changeme", "secret", "session", "session_secret",
    "cambiar-por-al-menos-32-caracteres-aleatorios",
})


class SettingsError(RuntimeError):
    pass


def _read_password() -> str:
    path = (os.environ.get("PANEL_PASSWORD_FILE") or "").strip()
    if path:
        p = Path(path)
        if not p.is_file():
            raise SettingsError(f"PANEL_PASSWORD_FILE no existe o no es un archivo")
        value = p.read_text(encoding="utf-8").strip()
        if not value:
            raise SettingsError("PANEL_PASSWORD_FILE está vacío")
        return value
    return (os.environ.get("PANEL_PASSWORD") or "").strip()


@dataclass(frozen=True)
class Settings:
    panel_user: str
    panel_password: str
    session_secret: str
    session_secure: bool
    session_hours: int
    snapshot_path: Path
    refresh_timeout: int
    refresh_interval_minutes: int
    timezone: str


def load_settings() -> Settings:
    user = (os.environ.get("PANEL_USER") or "").strip()
    password = _read_password()
    secret = (os.environ.get("SESSION_SECRET") or "").strip()
    secure_raw = (os.environ.get("SESSION_SECURE") or "true").strip().lower()
    session_secure = secure_raw in {"1", "true", "yes", "on"}
    try:
        hours = int(os.environ.get("SESSION_HOURS") or "12")
    except ValueError as exc:
        raise SettingsError("SESSION_HOURS debe ser un entero") from exc
    try:
        timeout = int(os.environ.get("REFRESH_TIMEOUT") or "420")
    except ValueError as exc:
        raise SettingsError("REFRESH_TIMEOUT debe ser un entero") from exc
    try:
        interval = int(os.environ.get("REFRESH_INTERVAL_MINUTES") or "0")
    except ValueError as exc:
        raise SettingsError("REFRESH_INTERVAL_MINUTES debe ser un entero") from exc

    if not user:
        raise SettingsError("PANEL_USER es obligatorio (sin valor por defecto)")
    if password.lower() in WEAK_PASSWORDS or password.lower() == user.lower():
        raise SettingsError(
            "PANEL_PASSWORD es obligatorio, no puede estar vacío ni ser una clave débil "
            "o de ejemplo, y no puede coincidir con el usuario"
        )
    if len(password) < 12:
        raise SettingsError("PANEL_PASSWORD debe tener al menos 12 caracteres")
    if secret in WEAK_SECRETS or len(secret) < 32:
        raise SettingsError("SESSION_SECRET es obligatorio y debe tener al menos 32 caracteres distintos de los ejemplos")
    if hours < 1 or hours > 168:
        raise SettingsError("SESSION_HOURS debe estar entre 1 y 168")
    if timeout < 30 or timeout > 1800:
        raise SettingsError("REFRESH_TIMEOUT debe estar entre 30 y 1800 segundos")
    if interval < 0:
        raise SettingsError("REFRESH_INTERVAL_MINUTES no puede ser negativo")
    if interval != 0 and interval < 15:
        raise SettingsError("Si habilita el intervalo, REFRESH_INTERVAL_MINUTES debe ser 0 (apagado) o al menos 15")

    snapshot = Path(os.environ.get("SNAPSHOT_PATH") or "/app/data/snapshot.json")
    return Settings(
        panel_user=user,
        panel_password=password,
        session_secret=secret,
        session_secure=session_secure,
        session_hours=hours,
        snapshot_path=snapshot,
        refresh_timeout=timeout,
        refresh_interval_minutes=interval,
        timezone=os.environ.get("TZ") or "America/Santiago",
    )
