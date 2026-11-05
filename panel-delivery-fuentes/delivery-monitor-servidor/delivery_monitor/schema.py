"""Validación liviana del JSON de los CLI y del snapshot (sin dependencias)."""
from __future__ import annotations

UBER_MONITOR_STATES = frozenset({"open", "closed", "paused", "not_visible"})
PYA_MONITOR_STATES = frozenset({
    "OPEN", "HIGH_DEMAND_MODE", "CLOSED", "INACTIVE",
    "OUTSIDE_SCHEDULE", "CHECKIN", "CHECKOUT", "NOT_FOUND",
})
STORE_STATUSES = frozenset({
    "abierta", "abierta_alta_demanda", "cerrada_por_horario", "pausada",
    "cerrada", "inactiva", "no_visible", "check_in", "desconocido",
})
DISPUTE_STATES = frozenset({"pendiente", "iniciada", "resuelta", "desconocido"})
SOURCE_STATUSES = frozenset({"ok", "error", "pending"})
PLATFORMS = frozenset({"uber", "pedidosya", "rappi"})


class SchemaError(ValueError):
    pass


def _need(row: dict, keys: tuple[str, ...], where: str) -> list[str]:
    missing = [k for k in keys if k not in row or row.get(k) in (None,)]
    return [f"{where}: falta {k}" for k in missing]


def validate_uber_monitor_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise SchemaError("uber monitor: se esperaba una lista JSON")
    out = []
    errors = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"uber monitor[{i}]: no es objeto")
            continue
        errors.extend(_need(row, ("store", "state", "id"), f"uber monitor[{i}]"))
        st = str(row.get("state") or "")
        if st and st not in UBER_MONITOR_STATES:
            errors.append(f"uber monitor[{i}]: state desconocido {st!r}")
        else:
            out.append(row)
    if not out and rows:
        raise SchemaError("; ".join(errors) or "uber monitor: filas inválidas")
    if not out:
        raise SchemaError("uber monitor: lista vacía tras una lectura que debería traer tiendas")
    return out


def validate_uber_dispute_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise SchemaError("uber disputes: se esperaba una lista JSON")
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if not row.get("order") and not row.get("store"):
            continue
        out.append(row)
    return out


def validate_pya_monitor_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise SchemaError("pedidosya monitor: se esperaba una lista JSON")
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if not row.get("vendor_id") or not row.get("name"):
            continue
        out.append(row)
    if not out:
        raise SchemaError("pedidosya monitor: lista vacía tras una lectura que debería traer tiendas")
    return out


def validate_pya_issue_tiles(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise SchemaError("pedidosya issues: se esperaba una lista JSON")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "type" not in row:
            continue
        out.append(row)
    return out


def snapshot_errors(snap: dict) -> list[str]:
    errs = []
    if not isinstance(snap, dict):
        return ["snapshot no es un objeto"]
    for k in ("generated_at", "timezone", "sources", "totals", "stores", "disputes"):
        if k not in snap:
            errs.append(f"falta {k}")
    if snap.get("timezone") != "America/Santiago":
        errs.append("timezone debe ser America/Santiago")
    sources = snap.get("sources") or {}
    for name, src in sources.items():
        if name not in PLATFORMS:
            errs.append(f"fuente desconocida {name}")
        st = (src or {}).get("status")
        if st not in SOURCE_STATUSES:
            errs.append(f"{name}: status inválido {st!r}")
        if st == "error" and src.get("stores_count") == 0:
            errs.append(f"{name}: un error no puede reportarse como 0 tiendas")
        if st == "pending" and src.get("stores_count") == 0:
            errs.append(f"{name}: pendiente no puede reportarse como 0 tiendas")
        if st != "ok" and src.get("stores_count") == 0:
            errs.append(f"{name}: sin lectura ok no puede ser 0")
    for i, store in enumerate(snap.get("stores") or []):
        if store.get("status") not in STORE_STATUSES:
            errs.append(f"stores[{i}]: status inválido")
        if store.get("platform") not in PLATFORMS:
            errs.append(f"stores[{i}]: platform inválida")
    for i, d in enumerate(snap.get("disputes") or []):
        if d.get("state") not in DISPUTE_STATES:
            errs.append(f"disputes[{i}]: state inválido")
    return errs
