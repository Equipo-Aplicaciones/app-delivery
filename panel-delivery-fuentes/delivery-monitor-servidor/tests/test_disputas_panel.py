import json
import os
import time
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app import deps
from app.disputas_app import app as disputas_app
from app.modules import credentials, disputas_panel, evidence

from test_modules import EVID_KEY, EVID_URL, ModulesBase, _RealClient, completed

UBER_COUNTERS = ("Pedidos con incidencias 2026-10-07..2026-11-05, 3 tiendas: missed=4, canceled=1, disputeInProgress=0, "
                 "disputeAccepted=1, disputeRejected=1, issueCharged=2, issueReported=9, potentialDeduction=0")
UBER_ROWS = {
    "pending": [
        {"store": "Tarragona - Centro", "order": "AA7A2", "requested": "11/05/2026, 8:30 PM", "tag": "ISSUE_CHARGED",
         "issue": "ISSUE_WITH_ITEMS", "chargeback": "$3990.00", "possible_chargeback": "", "workflow_uuid": "wf-1"},
        {"store": "Tarragona - Centro", "order": "BB111", "requested": "11/04/2026, 1:00 PM", "tag": "DISPUTE_ASSIGNED_TO_AGENT",
         "issue": "WRONG_ORDER", "chargeback": "$5000.00", "possible_chargeback": "", "workflow_uuid": "wf-2"},
    ],
    "accepted": [{"store": "Tarragona - Sur", "order": "CC222", "requested": "11/03/2026, 1:00 PM", "tag": "DISPUTE_ACCEPTED",
                  "issue": "ISSUE_WITH_ITEMS", "chargeback": "$2075.00", "possible_chargeback": "", "workflow_uuid": "wf-3"}],
    "rejected": [{"store": "Tarragona - Sur", "order": "DD333", "requested": "10/27/2026, 1:28 AM", "tag": "DISPUTE_DENIED",
                  "issue": "WRONG_ORDER", "chargeback": "$5980.00", "possible_chargeback": "", "workflow_uuid": "wf-4"}],
    "disputed": [],
}
PYA_TILES = [
    {"store": "TOTAL (2 tiendas)", "type": "CUSTOMER_COMPLAINTS", "orders": 12, "amount": "45000.00", "amount_type": "DEDUCTION", "orders_with_amount": 11},
    {"store": "TOTAL (2 tiendas)", "type": "AVOIDABLE_CANCELLATIONS", "orders": 2, "amount": "3000.00", "amount_type": "FEE", "orders_with_amount": 2},
]
PYA_ORDERS = [{"store": "Tarragona Ñuñoa", "order_id": "2355819567", "placed": "2026-11-05 13:10", "status": "DELIVERED",
               "subtotal": 12000, "fees_deductions": -3500, "issues": "CUSTOMER_COMPLAINTS:MISSING_ITEM:3500"}]


class DisputasBase(ModulesBase):
    def setUp(self):
        super().setUp()
        self.env2 = mock.patch.dict(os.environ, {"PANEL_AUTH": "false", "PANEL_USER": "", "PANEL_PASSWORD": "", "SESSION_SECRET": ""})
        self.env2.start()
        deps.reset_settings()
        disputas_panel._jobs.update({p: {"running": False} for p in disputas_panel.PLATFORMS})
        self.client = TestClient(disputas_app)
        self.pya_orders_blocked = False

    def tearDown(self):
        self.env2.stop()
        super().tearDown()

    def sessions(self):
        self.write_session("uber", "sid=abc")
        self.write_session("pedidosya", '{"access": "x"}')

    def cli(self, cmd, env):
        args = cmd[2:]
        if args[:1] == ["disputes"]:
            status = args[args.index("--status") + 1]
            return completed(cmd, 0, json.dumps(UBER_ROWS[status]), UBER_COUNTERS)
        if args[:1] == ["issues"]:
            return completed(cmd, 0, json.dumps(PYA_TILES), "Problemas de pedidos")
        if args[:1] == ["orders"]:
            if self.pya_orders_blocked:
                return completed(cmd, 1, "", "ERROR: POST https://vagw-api/query -> HTTP 403: perimeterx")
            return completed(cmd, 0, json.dumps(PYA_ORDERS), "1 pedidos")
        if args[:1] == ["dispute"]:
            return completed(cmd, 0, json.dumps({"order": "AA7A2", "problems": [], "variables": {"disputeSubmission": {"reason": "X"}},
                                                 "evidence_files": []}), "")
        return completed(cmd, 1, "", "sin mock")

    def refresh(self, platform, days=30):
        self.handler = self.cli
        r = self.client.post("/api/panel/refresh", json={"platform": platform, "days": days})
        self.assertEqual(r.status_code, 200, r.text)
        for _ in range(200):
            if not self.client.get(f"/api/panel/refresh?platform={platform}").json().get("running"):
                return
            time.sleep(0.02)
        self.fail("refresh no terminó")


class NoLoginTests(DisputasBase):
    def test_panel_opens_without_login(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/panel/meta").json()["login"], False)
        self.assertEqual(self.client.get("/api/credentials/status").status_code, 200)

    def test_login_can_be_turned_back_on(self):
        with mock.patch.dict(os.environ, {"PANEL_AUTH": "true", "PANEL_USER": "qa-modulos",
                                          "PANEL_PASSWORD": "clave-de-prueba-modulos-123",
                                          "SESSION_SECRET": "session-secret-modulos-1234567890"}):
            deps.reset_settings()
            self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)
            self.assertEqual(self.client.get("/api/panel/stats").status_code, 401)
            self.assertEqual(self.client.get("/api/credentials/status").status_code, 401)
        deps.reset_settings()

    def test_main_panel_still_requires_login_by_default(self):
        from app.main import app as main_app
        with mock.patch.dict(os.environ, {"PANEL_AUTH": "", "PANEL_USER": "qa-modulos",
                                          "PANEL_PASSWORD": "clave-de-prueba-modulos-123",
                                          "SESSION_SECRET": "session-secret-modulos-1234567890"}):
            deps.reset_settings()
            self.assertEqual(TestClient(main_app).get("/api/snapshot").status_code, 401)
        deps.reset_settings()


class UberPanelTests(DisputasBase):
    def test_states_from_uber_tags_and_stats(self):
        self.sessions()
        self.refresh("uber")
        s = self.client.get("/api/panel/stats?platform=uber").json()
        self.assertEqual(s["by_state"]["pendiente"]["count"], 1)
        self.assertEqual(s["by_state"]["abierta"]["count"], 1)
        self.assertEqual(s["by_state"]["ganada"]["count"], 1)
        self.assertEqual(s["by_state"]["perdida"]["count"], 1)
        self.assertEqual(s["by_state"]["ganada"]["amount_clp"], 2075)
        self.assertEqual(s["success_rate"], 50)
        self.assertEqual(s["uber_counters"]["issueReported"], 9)
        rows = self.client.get("/api/panel/disputes?platform=uber&estado=perdida").json()["rows"]
        self.assertEqual([r["order_id"] for r in rows], ["DD333"])
        everything = self.client.get("/api/panel/disputes?platform=uber&estado=todas").text
        self.assertNotIn("wf-1", everything)
        self.assertNotIn("workflow_uuid", everything)
        self.assertEqual(self.client.get("/api/panel/disputes?platform=uber&estado=x").status_code, 400)

    def test_missing_session_is_not_zero(self):
        self.refresh("uber")
        s = self.client.get("/api/panel/stats?platform=uber").json()
        self.assertEqual(s["status"], "missing_credentials")
        self.assertEqual(self.calls, [])

    def test_request_dry_run_records_prepared(self):
        self.sessions()
        self.write_snapshot({"stores": [{"platform": "uber", "store_id": "rest-1", "name": "Tarragona - Centro"}]})
        self.refresh("uber")
        r = self.client.post("/api/panel/request/uber/AA7A2", json={"reason": "STORE_EVIDENCE_AVAILABLE", "description": "Salió completo"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["dry_run"])
        self.assertEqual(r.json()["record"]["state"], "preparada")
        dispute_call = [c["cmd"] for c in self.calls if c["cmd"][2:3] == ["dispute"]][-1]
        self.assertIn("--dry-run", dispute_call)
        self.assertNotIn("--yes", dispute_call)
        self.assertEqual(self.client.get("/api/panel/stats?platform=uber").json()["prepared"], 1)
        r = self.client.post("/api/panel/request/uber/AA7A2", json={"reason": "STORE_EVIDENCE_AVAILABLE", "confirm": True})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(any("--yes" in c["cmd"] for c in self.calls))

    def test_uber_results_cannot_be_set_by_hand(self):
        r = self.client.post("/api/panel/record/uber/AA7A2", json={"state": "ganada"})
        self.assertEqual(r.status_code, 400)


class PyaPanelTests(DisputasBase):
    def test_tiles_orders_and_local_flow(self):
        self.sessions()
        self.write_snapshot({"stores": [{"platform": "pedidosya", "store_id": "PY_CL;77", "name": "Tarragona Ñuñoa"}]})
        self.refresh("pedidosya", 7)
        s = self.client.get("/api/panel/stats?platform=pedidosya").json()
        self.assertEqual(next(t for t in s["tiles"] if t["type"] == "CUSTOMER_COMPLAINTS")["orders"], 12)
        self.assertEqual(s["by_state"]["pendiente"]["count"], 1)
        rows = self.client.get("/api/panel/disputes?platform=pedidosya&estado=pendiente").json()["rows"]
        self.assertEqual(rows[0]["store_id"], "PY_CL;77")
        self.assertEqual(rows[0]["amount_clp"], 3500)
        r = self.client.post("/api/panel/request/pedidosya/2355819567", json={"reason": "PEDIDO_COMPLETO", "description": "Foto antes del despacho"})
        self.assertEqual(r.status_code, 200, r.text)
        pkg = r.json()["request"]
        self.assertIn("2355819567", pkg["texto_para_portal"])
        self.assertIn("$3.500", pkg["texto_para_portal"])
        self.assertEqual(self.client.post("/api/panel/record/pedidosya/2355819567", json={"state": "abierta"}).status_code, 200)
        self.assertEqual(self.client.get("/api/panel/disputes?platform=pedidosya&estado=abierta").json()["count"], 1)
        self.client.post("/api/panel/record/pedidosya/2355819567", json={"state": "ganada"})
        s = self.client.get("/api/panel/stats?platform=pedidosya").json()
        self.assertEqual(s["by_state"]["ganada"]["count"], 1)
        self.assertEqual(s["success_rate"], 100)
        self.assertEqual(self.client.post("/api/panel/record/pedidosya/2355819567", json={"state": "x"}).status_code, 400)

    def test_blocked_listing_keeps_tiles_and_manual_orders(self):
        self.sessions()
        self.pya_orders_blocked = True
        self.refresh("pedidosya", 7)
        s = self.client.get("/api/panel/stats?platform=pedidosya").json()
        self.assertEqual(s["orders_status"], "blocked")
        self.assertIn("anti-bots", s["orders_error"])
        self.assertTrue(s["tiles"])
        self.client.post("/api/panel/request/pedidosya/999888", json={"reason": "OTRO", "description": "Manual"})
        rows = self.client.get("/api/panel/disputes?platform=pedidosya&estado=pendiente").json()["rows"]
        self.assertEqual([(r["order_id"], r.get("manual")) for r in rows], [("999888", True)])

    def test_pya_reason_validation(self):
        r = self.client.post("/api/panel/request/pedidosya/123", json={"reason": "OTRO"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/panel/request/pedidosya/123", json={"reason": "NOPE"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/panel/order/pedidosya/..%2Fetc").status_code, 404)


class ManualImageAndKeyTests(DisputasBase):
    evidencia_key = ""

    def test_manual_search_without_key_says_not_configured(self):
        v = self.client.get("/api/panel/order/uber/AA7A2").json()
        self.assertEqual(v["app_evidence"]["status"], "not_configured")
        self.assertFalse(v["submit"]["can_prepare"])

    def test_evidence_key_is_probed_saved_and_never_returned(self):
        def handler(request):
            ok = request.headers.get("x-evidencia-key") == EVID_KEY
            if not ok:
                return httpx.Response(401, json={"error": "no"})
            return httpx.Response(200, json={"images": [{"id": "img-1", "created_at": "2026-11-05T20:00:00Z",
                                                         "url": "https://proyecto.supabase.co/storage/v1/object/sign/evidencia/a.jpg?token=FIRMA"}]})

        transport = httpx.MockTransport(handler)
        with mock.patch.object(evidence.httpx, "Client", lambda **kw: _RealClient(transport=transport, **kw)):
            bad = self.client.put("/api/credentials/evidencia", data={"value": "clave-mala"})
            self.assertEqual(bad.status_code, 422)
            self.assertFalse((self.tmp / "sessions" / "evidencia_api_key").exists())
            r = self.client.put("/api/credentials/evidencia", data={"value": EVID_KEY})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertNotIn(EVID_KEY, r.text)
            path = self.tmp / "sessions" / "evidencia_api_key"
            self.assertEqual(path.read_text(), EVID_KEY)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            v = self.client.get("/api/panel/order/uber/AA7A2")
            self.assertEqual(v.json()["app_evidence"]["status"], "ok")
            self.assertEqual(len(v.json()["app_evidence"]["images"]), 1)
            self.assertNotIn("FIRMA", v.text)
            self.assertNotIn(EVID_KEY, self.audit_text())
            status = self.client.get("/api/credentials/status?check=true").text
            self.assertNotIn(EVID_KEY, status)

    def test_env_key_cannot_be_overwritten_from_panel(self):
        with mock.patch.dict(os.environ, {"EVIDENCIA_API_KEY": "fija-por-entorno"}):
            deps.reset_settings()
            r = self.client.put("/api/credentials/evidencia", data={"value": "otra"})
            self.assertEqual(r.status_code, 409)
        deps.reset_settings()


if __name__ == "__main__":
    import unittest

    unittest.main()
