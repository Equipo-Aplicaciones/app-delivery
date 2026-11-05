"""Marca, exclusión y estado normalizado (hora Chile conceptual, no I/O)."""
from __future__ import annotations

import re
import unicodedata

STATUS_LABELS = {
    "abierta": "Abierta",
    "abierta_alta_demanda": "Abierta (alta demanda)",
    "cerrada_por_horario": "Cerrada por horario",
    "pausada": "Pausada",
    "cerrada": "Cerrada (otro motivo)",
    "inactiva": "Inactiva",
    "no_visible": "No visible",
    "check_in": "Check-in",
    "desconocido": "Desconocido",
}

OPEN_NOW_STATUSES = frozenset({"abierta", "abierta_alta_demanda"})
NOT_ENABLED_STATUSES = frozenset({"inactiva", "no_visible", "desconocido"})

# Locales que deben permanecer cerrados (reglas-de-oro-monitoreo-delivery).
EXCLUDED_PYA_IDS = frozenset({
    "616756", "612270", "59723", "68195", "611607", "612256",
    "59089", "616509", "616530",
})
EXCLUDED_UBER_NAMES = frozenset({
    "pollo stop la granja",
    "pollo stop rancagua",
    "pollo stop valle grande",
    "tarragona - locales criticos",
    "tarragona - arauco maipu",
})
EXCLUDED_RAPPI_NAMES = frozenset({
    "pollo stop concepcion",
    "elemental mall curico",
    "elemental mall del centro concepcion",
    "elemental la pintana - la pintana",
    "pollo stop rancagua",
    "pollo stop la granja",
    "elemental mall paseo rancagua",
})

_SCHEDULE_RE = re.compile(
    r"(opens\b|off[-\s]?hours|outside[_\s-]?schedule|fuera de horario|"
    r"outside schedule|closed until|horario)",
    re.I,
)


def fold(text: str) -> str:
    s = unicodedata.normalize("NFD", text or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def brand_of(name: str) -> str:
    n = fold(name)
    if "pollo stop" in n:
        return "Pollo Stop"
    if "elemental" in n:
        return "Elemental"
    if "tarragona" in n:
        return "Tarragona"
    return "Otra"


def is_excluded(platform: str, store_id: str | None, name: str) -> bool:
    n = fold(name)
    pid = str(store_id or "").strip()
    if platform == "pedidosya" and pid in EXCLUDED_PYA_IDS:
        return True
    if platform == "uber":
        if n in EXCLUDED_UBER_NAMES:
            return True
        if n.startswith("tarragona - arauco maipu"):
            return True
        if "locales criticos" in n:
            return True
    if platform == "rappi":
        if n in EXCLUDED_RAPPI_NAMES:
            return True
        if "cerrado no abrir" in n and "pollo stop" in n and "granja" in n:
            return True
    return False


def looks_like_schedule(reason: str) -> bool:
    return bool(reason and _SCHEDULE_RE.search(reason))


def classify_uber(row: dict) -> str:
    state = str(row.get("state") or "").strip().lower()
    reason = str(row.get("reason") or "")
    paused_until = str(row.get("paused_until") or "").strip()
    next_open = str(row.get("next_open") or "").strip()
    if state == "open":
        return "abierta"
    if state == "paused":
        return "pausada"
    if state == "not_visible":
        return "no_visible"
    if state == "closed":
        if looks_like_schedule(reason):
            return "cerrada_por_horario"
        if next_open and not paused_until and not reason.strip():
            return "cerrada_por_horario"
        return "cerrada"
    return "desconocido"


_PYA_MAP = {
    "OPEN": "abierta",
    "HIGH_DEMAND_MODE": "abierta_alta_demanda",
    "CLOSED": "pausada",
    "INACTIVE": "inactiva",
    "OUTSIDE_SCHEDULE": "cerrada_por_horario",
    "CHECKIN": "check_in",
    "CHECKOUT": "abierta",
    "NOT_FOUND": "desconocido",
}


def classify_pya(row: dict) -> str:
    raw = str(row.get("state") or "").strip().upper()
    return _PYA_MAP.get(raw, "desconocido")


def is_open_now(status: str) -> bool:
    return status in OPEN_NOW_STATUSES


def is_enabled(status: str) -> bool:
    """Habilitada en plataforma no implica abierta ahora."""
    return status not in NOT_ENABLED_STATUSES
