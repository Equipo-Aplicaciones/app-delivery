"""Adaptador PedidosYa: envuelve `pya.py monitor --json` e `issues --json`.

No cuenta reclamos como disputas pendientes. Solo listaría una disputa
'sin abrir' si un detalle de pedido confirmara isDisputeAllowed / dispute.status,
cosa que este refresh no hace pedido a pedido (PerimeterX y datos de cliente).
"""
from __future__ import annotations

import os

from ..classify import brand_of, classify_pya, is_enabled, is_excluded, is_open_now
from ..parseutil import iso_chile
from ..sanitize import sanitize
from ..schema import SchemaError, validate_pya_issue_tiles, validate_pya_monitor_rows
from .base import ProviderResult
from .runner import CliError, run_json_cli
from .uber import default_window

DEFAULT_SCRIPT = os.environ.get("PYA_CLI", "/app/clients/pya/pya.py")
DEFAULT_CWD = os.environ.get("PYA_CLI_CWD", "/app/clients/pya")
MONITOR_TIMEOUT = int(os.environ.get("PYA_MONITOR_TIMEOUT", "180"))
ISSUES_TIMEOUT = int(os.environ.get("PYA_ISSUES_TIMEOUT", "90"))

NO_DIRECT_LIST = (
    "PedidosYa no tiene un listado de disputas equivalente al de Uber. "
    "El comando `issues` entrega mosaicos de reclamos/descuentos (un reclamo no es "
    "una disputa pendiente). Solo se contaría como disputa 'sin abrir' si "
    "`order` confirmara isDisputeAllowed o dispute.status; este refresh no inspecciona "
    "pedidos uno a uno para no disparar PerimeterX ni tratar datos de clientes."
)


def normalize_store(row: dict) -> dict:
    name = str(row.get("name") or "")
    sid = str(row.get("vendor_id") or "")
    status = classify_pya(row)
    return {
        "platform": "pedidosya",
        "store_id": sid,
        "name": name,
        "brand": brand_of(name),
        "status": status,
        "status_raw": str(row.get("state") or ""),
        "open_now": is_open_now(status),
        "enabled": is_enabled(status),
        "reason": str(row.get("reason") or ""),
        "since": str(row.get("since") or "") or None,
        "until": str(row.get("until") or "") or None,
        "next_open": None,
        "next_close": None,
        "author": str(row.get("author") or "") or None,
        "slot": str(row.get("slot") or "") or None,
        "excluded": is_excluded("pedidosya", sid, name),
    }


def normalize_issue_tile(row: dict, window: dict) -> dict:
    return {
        "store": str(row.get("store") or ""),
        "type": str(row.get("type") or ""),
        "orders": row.get("orders"),
        "amount": row.get("amount"),
        "amount_type": row.get("amount_type"),
        "orders_with_amount": row.get("orders_with_amount"),
        "window_start": window["start"],
        "window_end": window["end"],
        "note": "reclamo agregado; no es una disputa pendiente confirmada",
    }


class PedidosYaAdapter:
    platform = "pedidosya"

    def __init__(self, script: str = DEFAULT_SCRIPT, cwd: str = DEFAULT_CWD, runner=run_json_cli):
        self.script = script
        self.cwd = cwd
        self.runner = runner

    def fetch(self) -> ProviderResult:
        fetched = iso_chile()
        start, end = default_window()
        window = {
            "start": start,
            "end": end,
            "label": f"ventana consultada {start} a {end} (America/Santiago)",
        }
        result = ProviderResult(
            platform="pedidosya",
            status="error",
            fetched_at=fetched,
            disputes_window=window,
            extra={"limitation": NO_DIRECT_LIST},
        )
        try:
            raw = self._monitor()
            result.stores = [normalize_store(r) for r in raw]
            result.status = "ok"
        except (CliError, SchemaError) as exc:
            result.error = sanitize(str(exc))
            result.stores = None
            result.status = "error"
        # Disputas: no hay listado. Se intenta issues solo como contexto de reclamos.
        try:
            tiles = self._issues(start, end)
            result.disputes = None
            result.disputes_status = "no_direct_list"
            result.extra = {
                **result.extra,
                "complaints_status": "ok",
                "complaint_tiles": [normalize_issue_tile(t, window) for t in tiles],
            }
        except (CliError, SchemaError) as exc:
            result.disputes = None
            result.disputes_status = "no_direct_list"
            result.disputes_error = sanitize(str(exc))
            result.extra = {
                **result.extra,
                "complaints_status": "error",
                "complaint_tiles": None,
            }
        return result

    def _monitor(self) -> list[dict]:
        out = self.runner(self.script, ["monitor", "--json"], self.cwd, MONITOR_TIMEOUT)
        return validate_pya_monitor_rows(out.data)

    def _issues(self, start: str, end: str) -> list[dict]:
        args = ["issues", "--json", "--start", start, "--end", end]
        out = self.runner(self.script, args, self.cwd, ISSUES_TIMEOUT)
        return validate_pya_issue_tiles(out.data)
