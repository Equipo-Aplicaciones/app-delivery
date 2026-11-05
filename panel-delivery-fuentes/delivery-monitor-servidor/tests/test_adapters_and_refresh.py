import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_monitor.adapters.base import ProviderResult
from delivery_monitor.adapters.runner import CliError, CliOutput
from delivery_monitor.adapters.uber import UberAdapter, normalize_dispute, normalize_store, parse_counters
from delivery_monitor.adapters.pya import NO_DIRECT_LIST, PedidosYaAdapter, normalize_store as pya_store
from delivery_monitor.adapters.rappi import RappiAdapter
from delivery_monitor.snapshot import build_snapshot


class FakeRunner:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, script, args, cwd, timeout):
        self.calls.append((script, tuple(args), cwd, timeout))
        key = args[0]
        item = self.mapping[key]
        if isinstance(item, Exception):
            raise item
        data, stderr = item
        return CliOutput(data=data, stderr=stderr, returncode=0)


UBER_MONITOR = [
    {"store": "Tarragona - El Llano", "state": "open", "reason": "", "paused_until": "", "next_open": "", "next_close": "2026-11-05 23:00", "id": "u-open"},
    {"store": "Tarragona - Centro", "state": "closed", "reason": "Opens Friday at 17:00", "paused_until": "", "next_open": "2026-11-06 17:00", "next_close": "", "id": "u-hours"},
    {"store": "Tarragona - Sur", "state": "paused", "reason": "PROBLEM_IN_RESTAURANT", "paused_until": "2026-11-05 18:00", "next_open": "", "next_close": "", "id": "u-pause"},
    {"store": "POLLO STOP LA GRANJA", "state": "paused", "reason": "POTENTIAL_CHURN", "paused_until": "2027-07-02 14:27", "next_open": "", "next_close": "", "id": "u-ex"},
    {"store": "Tarragona - Arauco Maipu", "state": "closed", "reason": "CCAR_RESTO_CLOSED", "paused_until": "", "next_open": "", "next_close": "", "id": "u-maipu"},
]

UBER_DISPUTES = [
    {
        "store": "Tarragona - Velasquez", "order": "E85BC", "requested": "11/04/2026, 3:30 PM",
        "tag": "ISSUE_CHARGED", "issue": "ISSUE_WITH_ITEMS", "sales": "$12090.00",
        "chargeback": "$798.00", "possible_chargeback": "", "workflow_uuid": "wf-1",
    }
]
UBER_DISPUTES_STDERR = "Pedidos con incidencias 2026-10-07..2026-11-05, 5 tiendas: missed=1, canceled=2, disputeInProgress=3, issueCharged=10\n"

PYA_MONITOR = [
    {"vendor_id": "597977", "name": "Tarragona El Llano", "state": "OPEN", "estado": "abierta", "reason": "", "since": "", "until": "", "author": "", "slot": "11:00-23:00"},
    {"vendor_id": "1", "name": "Tarragona Mall Plaza Calama", "state": "CLOSED", "estado": "cerrada temporal", "reason": "TOO_BUSY_KITCHEN", "since": "2026-11-05 16:00", "until": "2026-11-05 16:20", "author": "log_vendor_client", "slot": ""},
    {"vendor_id": "616756", "name": "Elemental - Valle Grande", "state": "INACTIVE", "estado": "inactiva", "reason": "inactivo", "since": "", "until": "", "author": "", "slot": ""},
    {"vendor_id": "99", "name": "Pollo Stop - Temuco", "state": "OUTSIDE_SCHEDULE", "estado": "fuera de horario", "reason": "", "since": "", "until": "", "author": "", "slot": ""},
]

PYA_ISSUES = [
    {"store": "TOTAL (4 tiendas)", "type": "CUSTOMER_COMPLAINT", "orders": 12, "amount": 45000, "amount_type": "DISCOUNT", "orders_with_amount": 8},
]


class UberAdapterTests(unittest.TestCase):
    def test_normalizes_and_parses_counters(self):
        runner = FakeRunner({
            "monitor": (UBER_MONITOR, ""),
            "disputes": (UBER_DISPUTES, UBER_DISPUTES_STDERR),
        })
        res = UberAdapter(runner=runner).fetch()
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.disputes_status, "ok")
        by_id = {s["store_id"]: s for s in res.stores}
        self.assertTrue(by_id["u-open"]["open_now"])
        self.assertEqual(by_id["u-hours"]["status"], "cerrada_por_horario")
        self.assertFalse(by_id["u-hours"]["open_now"])
        self.assertTrue(by_id["u-hours"]["enabled"])
        self.assertEqual(by_id["u-pause"]["status"], "pausada")
        self.assertTrue(by_id["u-ex"]["excluded"])
        self.assertTrue(by_id["u-maipu"]["excluded"])
        self.assertEqual(by_id["u-maipu"]["status"], "cerrada")
        self.assertEqual(res.disputes[0]["amount_clp"], 798)
        self.assertEqual(res.disputes[0]["ordered_at"], "2026-11-04 15:30")
        self.assertEqual(res.disputes[0]["state"], "pendiente")
        self.assertEqual(res.disputes[0]["order_id"], "E85BC")
        self.assertIsNone(res.disputes[0]["eligibility"])
        self.assertEqual(res.disputes_counters["issueCharged"], 10)
        self.assertIn("start", res.disputes_window)
        self.assertEqual(res.disputes_window["start"] < res.disputes_window["end"] or res.disputes_window["start"] <= res.disputes_window["end"], True)

    def test_auth_error_is_not_zero_stores(self):
        runner = FakeRunner({
            "monitor": CliError("HTTP 403 cookie vencida", returncode=1, auth=True),
            "disputes": CliError("HTTP 403", returncode=1, auth=True),
        })
        res = UberAdapter(runner=runner).fetch()
        self.assertEqual(res.status, "error")
        self.assertIsNone(res.stores)
        self.assertIsNone(res.disputes)
        d = res.source_dict()
        self.assertIsNone(d["stores_count"])
        self.assertNotEqual(d["stores_count"], 0)
        self.assertIn("403", res.error)


class PyaAdapterTests(unittest.TestCase):
    def test_complaints_are_not_unopened_disputes(self):
        runner = FakeRunner({
            "monitor": (PYA_MONITOR, ""),
            "issues": (PYA_ISSUES, ""),
        })
        res = PedidosYaAdapter(runner=runner).fetch()
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(res.stores), 4)
        by_id = {s["store_id"]: s for s in res.stores}
        self.assertEqual(by_id["1"]["status"], "pausada")
        self.assertEqual(by_id["99"]["status"], "cerrada_por_horario")
        self.assertTrue(by_id["616756"]["excluded"])
        self.assertEqual(res.disputes_status, "no_direct_list")
        self.assertIsNone(res.disputes)
        tiles = res.extra["complaint_tiles"]
        self.assertEqual(tiles[0]["orders"], 12)
        self.assertIn("no es una disputa", tiles[0]["note"])
        self.assertIn("no tiene un listado", res.extra["limitation"])
        self.assertIn("listado", NO_DIRECT_LIST)

    def test_issues_403_does_not_invent_metrics(self):
        runner = FakeRunner({
            "monitor": (PYA_MONITOR, ""),
            "issues": CliError("HTTP 403 PerimeterX", returncode=1, auth=True),
        })
        res = PedidosYaAdapter(runner=runner).fetch()
        self.assertEqual(res.status, "ok")
        self.assertIsNotNone(res.stores)
        self.assertEqual(res.disputes_status, "no_direct_list")
        self.assertIsNone(res.disputes)
        self.assertEqual(res.extra["complaints_status"], "error")
        self.assertIsNone(res.extra["complaint_tiles"])
        self.assertIn("403", res.disputes_error)


class RappiTests(unittest.TestCase):
    def test_pending_has_no_invented_counts(self):
        res = RappiAdapter().fetch()
        self.assertEqual(res.status, "pending")
        self.assertIsNone(res.stores)
        self.assertIsNone(res.disputes)
        d = res.source_dict()
        self.assertIsNone(d["stores_count"])
        self.assertNotEqual(d["stores_count"], 0)
        self.assertIn("pendiente", res.error.lower() or "pending")


class SnapshotMergeTests(unittest.TestCase):
    def test_error_provider_does_not_add_zero_platform_total(self):
        uber = ProviderResult("uber", "error", "2026-11-05T16:00:00-03:00", error="HTTP 403", stores=None, disputes=None, disputes_status="error")
        pya = PedidosYaAdapter(runner=FakeRunner({"monitor": (PYA_MONITOR, ""), "issues": (PYA_ISSUES, "")})).fetch()
        rappi = RappiAdapter().fetch()
        snap = build_snapshot([uber, pya, rappi], generated_at="2026-11-05T16:40:00-03:00")
        self.assertEqual(snap["sources"]["uber"]["status"], "error")
        self.assertIsNone(snap["sources"]["uber"]["stores_count"])
        self.assertEqual(snap["totals"]["stores"], 4)
        self.assertIsNone(snap["totals"]["by_platform"]["uber"]["stores"])
        self.assertEqual(snap["totals"]["by_platform"]["pedidosya"]["stores"], 4)
        self.assertIsNone(snap["totals"]["by_platform"]["rappi"]["stores"])
        self.assertEqual(snap["totals"]["disputes_unopened"], 0)  # none confirmed
        self.assertIsNone(snap["totals"]["disputes_by_platform"]["pedidosya"])
        self.assertIsNone(snap["totals"]["disputes_by_platform"]["rappi"])
        self.assertTrue(snap["complaint_tiles"])
        self.assertEqual(snap["timezone"], "America/Santiago")

    def test_uber_disputes_merge_and_window(self):
        uber = UberAdapter(runner=FakeRunner({
            "monitor": (UBER_MONITOR, ""),
            "disputes": (UBER_DISPUTES, UBER_DISPUTES_STDERR),
        })).fetch()
        pya = PedidosYaAdapter(runner=FakeRunner({
            "monitor": (PYA_MONITOR, ""),
            "issues": CliError("HTTP 403 PerimeterX", returncode=1, auth=True),
        })).fetch()
        snap = build_snapshot([uber, pya, RappiAdapter().fetch()], generated_at="2026-11-05T16:40:00-03:00")
        self.assertEqual(snap["totals"]["disputes_unopened"], 1)
        self.assertEqual(snap["disputes"][0]["platform"], "uber")
        self.assertEqual(len(snap["stores"]), 5 + 4)
        self.assertEqual(snap["complaint_tiles"], [])
        self.assertIn("start", snap["sources"]["uber"]["disputes_window"])


class CounterParseTests(unittest.TestCase):
    def test_parse_counters(self):
        c, a, b = parse_counters(UBER_DISPUTES_STDERR)
        self.assertEqual(a, "2026-10-07")
        self.assertEqual(b, "2026-11-05")
        self.assertEqual(c["disputeInProgress"], 3)


class NormalizeUnitTests(unittest.TestCase):
    def test_dispute_amount(self):
        d = normalize_dispute(UBER_DISPUTES[0], {"start": "2026-10-07", "end": "2026-11-05"})
        self.assertEqual(d["amount_clp"], 798)
        self.assertEqual(d["amount_display"], "$798")

    def test_store_helpers(self):
        s = normalize_store(UBER_MONITOR[1])
        self.assertEqual(s["status"], "cerrada_por_horario")
        p = pya_store(PYA_MONITOR[1])
        self.assertEqual(p["author"], "log_vendor_client")


if __name__ == "__main__":
    unittest.main()
