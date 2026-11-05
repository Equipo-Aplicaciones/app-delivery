"""Parsers de montos CLP y fechas hacia hora Chile."""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Santiago")


def now_chile() -> dt.datetime:
    return dt.datetime.now(TZ)


def iso_chile(when: dt.datetime | None = None) -> str:
    d = when or now_chile()
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ).isoformat(timespec="seconds")


def chile_date(when: dt.datetime | None = None) -> str:
    return (when or now_chile()).strftime("%Y-%m-%d")


def parse_clp(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    if isinstance(value, dict):
        return parse_clp(value.get("amount"))
    s = str(value).replace("CLP", "").replace("$", "").strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    try:
        return int(round(float(s)))
    except ValueError:
        digits = re.sub(r"[^\d-]", "", s)
        if digits in ("", "-"):
            return None
        try:
            return int(digits)
        except ValueError:
            return None


def format_clp(n: int | None) -> str:
    if n is None:
        return ""
    return f"${n:,}".replace(",", ".")


def parse_requested(value) -> str:
    """Normaliza fecha de pedido a 'YYYY-MM-DD HH:MM' (America/Santiago si trae zona)."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        v = v / 1000 if v > 1e11 else v
        d = dt.datetime.fromtimestamp(v, dt.timezone.utc).astimezone(TZ)
        return d.strftime("%Y-%m-%d %H:%M")
    s = str(value).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", s)
    if m:
        return m.group(1)
    formats = (
        "%m/%d/%Y, %I:%M %p",
        "%m/%d/%Y, %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    )
    for fmt in formats:
        try:
            d = dt.datetime.strptime(s, fmt)
            if fmt.endswith("Z"):
                d = d.replace(tzinfo=dt.timezone.utc).astimezone(TZ)
            return d.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    try:
        iso = s.replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(iso)
        if d.tzinfo:
            d = d.astimezone(TZ)
        return d.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return s
