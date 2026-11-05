"""Sesión firmada en cookie HttpOnly. Nada va a localStorage ni a la URL."""
from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings

COOKIE_NAME = "dm_session"
_login_hits: dict[str, list[float]] = defaultdict(list)


def _signer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="delivery-monitor-panel")


def issue_session(response: Response, settings: Settings, username: str) -> None:
    token = _signer(settings).dumps({"u": username})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.session_secure,
        samesite="strict",
        path="/",
    )


def clear_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        samesite="strict",
        secure=settings.session_secure,
        httponly=True,
    )


def current_user(request: Request, settings: Settings) -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = _signer(settings).loads(raw, max_age=settings.session_hours * 3600)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    user = data.get("u") if isinstance(data, dict) else None
    if user != settings.panel_user:
        return None
    return str(user)


def require_user(request: Request, settings: Settings) -> str:
    user = current_user(request, settings)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    u1 = username.encode("utf-8")
    u2 = settings.panel_user.encode("utf-8")
    p1 = password.encode("utf-8")
    p2 = settings.panel_password.encode("utf-8")
    umax = max(len(u1), len(u2), 1)
    pmax = max(len(p1), len(p2), 1)
    user_ok = hmac.compare_digest(u1.ljust(umax, b"\0"), u2.ljust(umax, b"\0")) and len(u1) == len(u2)
    pass_ok = hmac.compare_digest(p1.ljust(pmax, b"\0"), p2.ljust(pmax, b"\0")) and len(p1) == len(p2)
    return bool(user_ok and pass_ok)


def allow_login_attempt(ip: str, limit: int = 5, window: float = 900.0) -> bool:
    now = time.monotonic()
    hits = [t for t in _login_hits.get(ip, []) if now - t < window]
    if len(hits) >= limit:
        _login_hits[ip] = hits
        return False
    hits.append(now)
    _login_hits[ip] = hits
    return True
