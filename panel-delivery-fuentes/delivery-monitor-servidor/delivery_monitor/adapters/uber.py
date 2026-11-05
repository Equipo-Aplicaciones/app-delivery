"""Adaptador Uber: envuelve `uber.py monitor --json` y `uber.py disputes --json`."""
from __future__ import annotations

import datetime as dt
import os
import re

from ..classify import brand_of, classify_uber, is_enabled, is_excluded, is_open_now
from ..parseutil import format_clp, iso_chile, now_chile, parse_clp, parse_requested
from ..sanitize import sanitize
from ..schema import SchemaError, validate_uber_dispute_rows, validate_uber_monitor_rows
from .base import ProviderResult
from .runner import CliError, run_json_cli

DEFAULT_SCRIPT = os.environ.get("UBER_CLI", "/app/clients/uber/uber.py")
DEFAULT_CWD = os.environ.get("UBER_CLI_CWD", "/app/clients/uber")
MONITOR_TIMEOUT = int(os.environ.get("UBER_MONITOR_TIMEOUT", "180"))
DISPUTES_TIMEOUT = int(os.environ.get("UBER_DISPUTES_TIMEOUT", "360"))
DISPUTES_MAX = int(os.environ.get("UBER_DISPUTES_MAX", "1000"))
WINDOW_DAYS = 29

_COUNTER_RE = re.compile(
    r"Pedidos con incidencias\s+(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2}),\s+(\d+)\s+tiendas:\s+(.+)"
)


def default_window(today: dt.date | None = None) -> tuple[str, str]:
    day = today or now_chile().date()
    start = day - dt.timedelta(days=WINDOW_DAYS)
    return str(start), str(day)


def parse_counters(stderr: str) -> tuple[dict | None, str | None, str | None]:
    for line in (stderr or "").splitlines():
        m = _COUNTER_RE.search(line)
        if not m:
            continue
        counters = {}
        for part in m.group(4).split(","):
            part = part.strip()
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            try:
                counters[k.strip()] = int(v.strip())
            except ValueError:
                counters[k.strip()] = v.strip()
        return counters, m.group(1), m.group(2)
    return None, None, None


def normalize_store(row: dict) -> dict:
    name = str(row.get("store") or "")
    sid = str(row.get("id") or "")
    status = classify_uber(row)
    until = str(row.get("paused_until") or "").strip() or None
    next_open = str(row.get("next_open") or "").strip() or None
    next_close = str(row.get("next_close") or "").strip() or None
    return {
        "platform": "uber",
        "store_id": sid,
        "name": name,
        "brand": brand_of(name),
        "status": status,
        "status_raw": str(row.get("state") or ""),
        "open_now": is_open_now(status),
        "enabled": is_enabled(status),
        "reason": str(row.get("reason") or ""),
        "since": None,
        "until": until,
        "next_open": next_open,
        "next_close": next_close,
        "author": None,
        "slot": None,
        "excluded": is_excluded("uber", sid, name),
    }


def normalize_dispute(row: dict, window: dict) -> dict:
    name = str(row.get("store") or "")
    amount = parse_clp(row.get("chargeback"))
    if amount is None:
        amount = parse_clp(row.get("possible_chargeback"))
    tag = str(row.get("tag") or "")
    state = "pendiente"
    if "DISPUTE_ACCEPTED" in tag or "DISPUTE_REJECTED" in tag:
        state = "resuelta"
    elif "DISPUTED" in tag or "DISPUTE_IN_PROGRESS" in tag:
        state = "iniciada"
    return {
        "platform": "uber",
        "store_name": name,
        "brand": brand_of(name),
        "order_id": str(row.get("order") or ""),
        "workflow_uuid": str(row.get("workflow_uuid") or "") or None,
        "ordered_at": parse_requested(row.get("requested")),
        "amount_clp": amount,
        "amount_display": format_clp(amount) if amount is not None else str(row.get("chargeback") or row.get("possible_chargeback") or ""),
        "issue": str(row.get("issue") or ""),
        "tag": tag,
        "state": state,
        "eligibility": row.get("eligibility") if isinstance(row.get("eligibility"), str) else None,
        "window_start": window["start"],
        "window_end": window["end"],
    }


class UberAdapter:
    platform = "uber"

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
            "label": f"últimos 30 días ({start} a {end}, America/Santiago)",
        }
        result = ProviderResult(
            platform="uber",
            status="error",
            fetched_at=fetched,
            disputes_window=window,
        )
        try:
            raw_stores = self._monitor()
            result.stores = [normalize_store(r) for r in raw_stores]
            result.status = "ok"
        except (CliError, SchemaError) as exc:
            result.error = sanitize(str(exc))
            result.stores = None
            result.status = "error"
        try:
            rows, counters, truncated = self._disputes(start, end)
            result.disputes = [normalize_dispute(r, window) for r in rows]
            result.disputes_status = "ok"
            result.disputes_counters = counters
            result.disputes_truncated = truncated
        except (CliError, SchemaError) as exc:
            result.disputes = None
            result.disputes_status = "error"
            result.disputes_error = sanitize(str(exc))
        return result

    def _monitor(self) -> list[dict]:
        out = self.runner(self.script, ["monitor", "--json"], self.cwd, MONITOR_TIMEOUT)
        return validate_uber_monitor_rows(out.data)

    def _disputes(self, start: str, end: str) -> tuple[list[dict], dict | None, bool]:
        args = [
            "disputes", "--json", "--status", "pending",
            "--start", start, "--end", end, "--max", str(DISPUTES_MAX),
        ]
        out = self.runner(self.script, args, self.cwd, DISPUTES_TIMEOUT)
        rows = validate_uber_dispute_rows(out.data)
        counters, c_start, c_end = parse_counters(out.stderr)
        truncated = len(rows) >= DISPUTES_MAX
        if counters is None:
            counters = {}
        if c_start and c_end:
            counters = {**counters, "_window_start": c_start, "_window_end": c_end}
        return rows, counters or None, truncated
