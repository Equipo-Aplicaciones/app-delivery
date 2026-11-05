import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_monitor.classify import (
    brand_of, classify_pya, classify_uber, is_enabled, is_excluded, is_open_now,
)


class BrandTests(unittest.TestCase):
    def test_brands(self):
        self.assertEqual(brand_of("Tarragona - El Llano"), "Tarragona")
        self.assertEqual(brand_of("POLLO STOP TEMUCO"), "Pollo Stop")
        self.assertEqual(brand_of("Elemental – Valle Grande"), "Elemental")
        self.assertEqual(brand_of("Local misterioso"), "Otra")


class ExcludedTests(unittest.TestCase):
    def test_pya_by_id(self):
        self.assertTrue(is_excluded("pedidosya", "616756", "Elemental - Valle Grande"))
        self.assertFalse(is_excluded("pedidosya", "597977", "Tarragona El Llano"))

    def test_uber_by_name(self):
        self.assertTrue(is_excluded("uber", "x", "POLLO STOP LA GRANJA"))
        self.assertTrue(is_excluded("uber", "x", "Tarragona - Arauco Maipu"))
        self.assertTrue(is_excluded("uber", "x", "Tarragona - Locales Criticos"))
        self.assertFalse(is_excluded("uber", "x", "Tarragona - El Llano"))


class UberClassifyTests(unittest.TestCase):
    def test_open(self):
        self.assertEqual(classify_uber({"state": "open"}), "abierta")

    def test_paused(self):
        self.assertEqual(classify_uber({"state": "paused", "reason": "PROBLEM_IN_RESTAURANT"}), "pausada")

    def test_not_visible(self):
        self.assertEqual(classify_uber({"state": "not_visible"}), "no_visible")

    def test_closed_by_hours_opens(self):
        self.assertEqual(classify_uber({"state": "closed", "reason": "Opens Friday at 5:00 PM"}), "cerrada_por_horario")

    def test_closed_other_reason(self):
        self.assertEqual(classify_uber({"state": "closed", "reason": "CCAR_RESTO_CLOSED"}), "cerrada")

    def test_closed_empty_reason_with_next_open(self):
        self.assertEqual(
            classify_uber({"state": "closed", "reason": "", "next_open": "2026-11-05 17:00", "paused_until": ""}),
            "cerrada_por_horario",
        )

    def test_closed_empty_no_next_open(self):
        self.assertEqual(classify_uber({"state": "closed", "reason": ""}), "cerrada")

    def test_unknown_state(self):
        self.assertEqual(classify_uber({"state": "weird"}), "desconocido")


class PyaClassifyTests(unittest.TestCase):
    def test_map(self):
        self.assertEqual(classify_pya({"state": "OPEN"}), "abierta")
        self.assertEqual(classify_pya({"state": "HIGH_DEMAND_MODE"}), "abierta_alta_demanda")
        self.assertEqual(classify_pya({"state": "CLOSED"}), "pausada")
        self.assertEqual(classify_pya({"state": "OUTSIDE_SCHEDULE"}), "cerrada_por_horario")
        self.assertEqual(classify_pya({"state": "INACTIVE"}), "inactiva")
        self.assertEqual(classify_pya({"state": "CHECKIN"}), "check_in")

    def test_open_vs_enabled(self):
        self.assertTrue(is_open_now("abierta"))
        self.assertTrue(is_open_now("abierta_alta_demanda"))
        self.assertFalse(is_open_now("cerrada_por_horario"))
        self.assertTrue(is_enabled("cerrada_por_horario"))
        self.assertTrue(is_enabled("pausada"))
        self.assertFalse(is_enabled("inactiva"))
        self.assertFalse(is_enabled("no_visible"))
        self.assertFalse(is_open_now("pausada"))


if __name__ == "__main__":
    unittest.main()
