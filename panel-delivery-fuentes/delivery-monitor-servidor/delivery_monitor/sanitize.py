"""Redacta secretos de textos que puedan ir al snapshot o a logs."""
from __future__ import annotations

import re

_SECRET = re.compile(
    r"(?i)(cookie|authorization|bearer|token|refresh_token|access_token|"
    r"password|passwd|secret|sid|jwt)([=:\s]+)([^\s,;]+)"
)
_LONG_B64 = re.compile(r"\b[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")


def sanitize(text: str | None, limit: int = 400) -> str:
    if not text:
        return ""
    s = _SECRET.sub(r"\1\2***", text)
    s = _LONG_B64.sub("[redacted-jwt]", s)
    s = s.replace("\n", " ").strip()
    if len(s) > limit:
        return s[: limit - 3] + "..."
    return s


def looks_like_auth_failure(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    markers = (
        "401", "403", "unauthorized", "cookie vencida", "forbidden",
        "perimeterx", "captcha", "no-json", "access denied", "unauthenticated",
        "token-refresh", "expired",
    )
    return any(m in t for m in markers)
