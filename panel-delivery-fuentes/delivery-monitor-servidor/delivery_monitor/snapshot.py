"""Arma el snapshot normalizado a partir de los resultados de cada adaptador."""
from __future__ import annotations

import os
from collections import Counter

from .adapters.base import ProviderResult
from .classify import STATUS_LABELS
from .parseutil import iso_chile
from .schema import snapshot_errors

INTEGRATION = {
    "note": (
        "Cada plataforma vive en su adaptador y llama a su CLI por subproceso "
        "(así no se mezclan los api_client.py homónimos). Para sumar un proveedor "
        "nuevo: implementar fetch() -> ProviderResult, registrarlo en "
        "delivery_monitor.adapters.ADAPTERS y volver a correr refresh.py."
    ),
    "wired": [
        {
            "id": "uber",
            "module": "delivery_monitor.adapters.uber",
            "cli": os.environ.get("UBER_CLI", "/app/clients/uber/uber.py"),
            "reads": ["monitor --json", "disputes --json --status pending"],
            "writes_not_used": ["pause", "activate", "soldout", "instock", "activate-menu", "dispute"],
        },
        {
            "id": "pedidosya",
            "module": "delivery_monitor.adapters.pya",
            "cli": os.environ.get("PYA_CLI", "/app/clients/pya/pya.py"),
            "reads": ["monitor --json", "issues --json"],
            "writes_not_used": ["pause", "activate", "soldout", "instock", "activate-menu"],
            "dispute_gap": "Sin listado de disputas; `order` confirma elegibilidad por pedido y no se recorre aquí.",
        },
        {
            "id": "rappi",
            "module": "delivery_monitor.adapters.rappi",
            "cli": None,
            "status": "pending",
            "reads": [],
            "note": "API vista en el portal; sin credenciales/CLI en este proyecto.",
        },
    ],
    "future_reads": [
        "uber soldout-report / sales / hours",
        "pedidosya soldout-report / sales / hours / orders / order",
        "rappi stores-router + store-status-detail cuando haya CLI o token renovable",
    ],
}


def _count_by(rows: list[dict], key: str) -> dict:
    return dict(Counter(r.get(key) for r in rows))


def build_snapshot(results: list[ProviderResult], generated_at: str | None = None) -> dict:
    sources = {}
    stores: list[dict] = []
    disputes: list[dict] = []
    for res in results:
        sources[res.platform] = res.source_dict()
        if res.status == "ok" and isinstance(res.stores, list):
            stores.extend(res.stores)
        if res.disputes_status == "ok" and isinstance(res.disputes, list):
            disputes.extend(res.disputes)

    stores.sort(key=lambda s: (
        0 if s.get("excluded") and s.get("open_now") else
        1 if not s.get("open_now") else 2,
        {"pausada": 0, "cerrada": 1, "inactiva": 2, "no_visible": 3,
         "check_in": 4, "cerrada_por_horario": 5, "desconocido": 6,
         "abierta_alta_demanda": 7, "abierta": 8}.get(s.get("status"), 9),
        s.get("platform") or "",
        s.get("name") or "",
    ))
    disputes.sort(key=lambda d: (d.get("ordered_at") or "", d.get("store_name") or ""), reverse=True)

    by_status = _count_by(stores, "status")
    totals = {
        "stores": len(stores),
        "open_now": sum(1 for s in stores if s.get("open_now")),
        "enabled": sum(1 for s in stores if s.get("enabled")),
        "paused": by_status.get("pausada", 0),
        "closed_schedule": by_status.get("cerrada_por_horario", 0),
        "closed_other": by_status.get("cerrada", 0),
        "inactive": by_status.get("inactiva", 0),
        "not_visible": by_status.get("no_visible", 0),
        "excluded": sum(1 for s in stores if s.get("excluded")),
        "excluded_open_now": sum(1 for s in stores if s.get("excluded") and s.get("open_now")),
        "by_status": by_status,
        "by_brand": _count_by(stores, "brand"),
        "by_platform": {},
        "disputes_unopened": len(disputes),
        "disputes_by_platform": {},
    }
    for res in results:
        entry = {"status": res.status, "stores": None, "disputes": None, "disputes_status": res.disputes_status}
        if res.status == "ok" and isinstance(res.stores, list):
            entry["stores"] = len(res.stores)
            entry["by_status"] = _count_by(res.stores, "status")
            entry["open_now"] = sum(1 for s in res.stores if s.get("open_now"))
        if res.disputes_status == "ok" and isinstance(res.disputes, list):
            entry["disputes"] = len(res.disputes)
        totals["by_platform"][res.platform] = entry
        totals["disputes_by_platform"][res.platform] = (
            len(res.disputes) if res.disputes_status == "ok" and isinstance(res.disputes, list) else None
        )

    complaints = []
    for res in results:
        tiles = (res.extra or {}).get("complaint_tiles")
        if tiles:
            complaints.extend(tiles)

    snap = {
        "generated_at": generated_at or iso_chile(),
        "timezone": "America/Santiago",
        "sources": sources,
        "totals": totals,
        "stores": stores,
        "disputes": disputes,
        "complaint_tiles": complaints,
        "integration": INTEGRATION,
        "status_labels": STATUS_LABELS,
    }
    errs = snapshot_errors(snap)
    if errs:
        raise ValueError("snapshot inválido: " + "; ".join(errs))
    return snap
