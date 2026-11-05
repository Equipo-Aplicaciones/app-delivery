import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_monitor.parseutil import format_clp, parse_clp, parse_requested
from delivery_monitor.sanitize import looks_like_auth_failure, sanitize
from delivery_monitor.schema import (
    SchemaError, snapshot_errors, validate_pya_monitor_rows,
    validate_uber_dispute_rows, validate_uber_monitor_rows,
)


class ParseTests(unittest.TestCase):
    def test_clp_uber_format(self):
        self.assertEqual(parse_clp("$798.00"), 798)
        self.assertEqual(parse_clp("$9990.00"), 9990)
        self.assertEqual(parse_clp(12450), 12450)
        self.assertEqual(parse_clp({"amount": 100}), 100)
        self.assertIsNone(parse_clp(""))
        self.assertIsNone(parse_clp(None))

    def test_format_clp(self):
        self.assertEqual(format_clp(12345), "$12.345")

    def test_requested(self):
        self.assertEqual(parse_requested("11/04/2026, 3:30 PM"), "2026-11-04 15:30")
        self.assertEqual(parse_requested("2026-11-04 15:30"), "2026-11-04 15:30")


class SanitizeTests(unittest.TestCase):
    def test_redacts_cookie_and_bearer(self):
        s = sanitize("Cookie: abcdef.secretvalue Authorization: Bearer eyJabc.def.ghi")
        self.assertNotIn("abcdef.secretvalue", s)
        self.assertIn("***", s)

    def test_auth_markers(self):
        self.assertTrue(looks_like_auth_failure("HTTP 403 PerimeterX captcha"))
        self.assertTrue(looks_like_auth_failure("401 cookie vencida"))
        self.assertFalse(looks_like_auth_failure("Resumen: {'OPEN': 10}"))


class SchemaTests(unittest.TestCase):
    def test_uber_monitor_ok(self):
        rows = validate_uber_monitor_rows([
            {"store": "Tarragona - Centro", "state": "open", "reason": "", "id": "u1"},
        ])
        self.assertEqual(len(rows), 1)

    def test_uber_monitor_empty_is_error(self):
        with self.assertRaises(SchemaError):
            validate_uber_monitor_rows([])

    def test_uber_monitor_not_list(self):
        with self.assertRaises(SchemaError):
            validate_uber_monitor_rows({"error": 403})

    def test_pya_monitor_requires_name(self):
        with self.assertRaises(SchemaError):
            validate_pya_monitor_rows([{"vendor_id": "1"}])

    def test_disputes_accepts_list(self):
        rows = validate_uber_dispute_rows([
            {"store": "Tarragona - Centro", "order": "ABC12", "chargeback": "$100.00"},
        ])
        self.assertEqual(len(rows), 1)

    def test_snapshot_rejects_error_as_zero(self):
        errs = snapshot_errors({
            "generated_at": "2026-11-05T16:00:00-03:00",
            "timezone": "America/Santiago",
            "sources": {"uber": {"status": "error", "stores_count": 0}},
            "totals": {},
            "stores": [],
            "disputes": [],
        })
        self.assertTrue(any("0 tiendas" in e or "no puede ser 0" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
