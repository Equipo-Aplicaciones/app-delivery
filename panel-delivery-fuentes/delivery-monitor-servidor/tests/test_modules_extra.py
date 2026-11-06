import datetime as dt
import json
import os
from unittest import mock

from app.modules import agents, automations

from test_modules import ModulesBase, completed

STORES = [
    {"platform": "uber", "store_id": "uuid-1", "name": "Tarragona Centro", "brand": "Tarragona",
     "status": "closed_unexpected", "open_now": False, "workflow_uuid": "INTERNO-NO-SALE"},
    {"platform": "pedidosya", "store_id": "PY_CL;77", "name": "Tarragona Ñuñoa", "brand": "Tarragona",
     "status": "open", "open_now": True},
]


class ExtraBase(ModulesBase):
    def setUp(self):
        super().setUp()
        agents._hits.clear()
        agents._last_seen.clear()
        automations._running.clear()
        automations._last_started.clear()

    def sessions(self):
        self.write_session("uber", "sid=abc")
        self.write_session("pedidosya", '{"token": "x"}')

    def cli_args(self, i=-1):
        return self.calls[i]["cmd"][2:]


class AuthExtraTests(ExtraBase):
    ROUTES = [
        ("get", "/api/stores"), ("get", "/api/stores/meta/options"), ("post", "/api/stores/activate"),
        ("post", "/api/stores/pause"), ("get", "/api/catalog/soldout"), ("post", "/api/catalog/soldout"),
        ("post", "/api/catalog/instock"), ("post", "/api/catalog/activate-menu"), ("get", "/api/reports"),
        ("post", "/api/reports/run"), ("get", "/api/reports/jobs/x"), ("get", "/api/reports/jobs/x/download"),
        ("get", "/api/automations"), ("post", "/api/automations"), ("post", "/api/automations/x/run"),
        ("patch", "/api/automations/x"), ("delete", "/api/automations/x"), ("get", "/api/agents"),
        ("post", "/api/agents"), ("delete", "/api/agents/x"),
    ]

    def test_all_require_session(self):
        for method, path in self.ROUTES:
            with self.subTest(route=f"{method} {path}"):
                kwargs = {"json": {}} if method in ("post", "patch") else {}
                self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, 401)
        self.assertEqual(self.calls, [])


class StoresTests(ExtraBase):
    def test_list_filters_and_hides_internal_fields(self):
        self.login()
        self.write_snapshot({"stores": STORES})
        data = self.client.get("/api/stores?platform=uber").json()
        self.assertEqual(data["count"], 1)
        self.assertNotIn("workflow_uuid", json.dumps(data))
        self.assertEqual(self.client.get("/api/stores?q=ñuñoa").json()["count"], 1)

    def test_pause_dry_run_never_sends_yes(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 0, '[{"store": "Tarragona Centro", "payload": {}}]')
        r = self.client.post("/api/stores/pause", json={"platform": "uber", "store_ids": ["uuid-1"],
                                                         "duration": "30", "reason": "OTHER"})
        self.assertEqual(r.status_code, 200, r.text)
        args = self.cli_args()
        self.assertIn("--dry-run", args)
        self.assertNotIn("--yes", args)
        self.assertEqual(args[:1], ["pause"])
        self.assertIn("--duration", args)
        self.assertTrue(r.json()["dry_run"])
        self.assertIn('"dry_run": true', self.audit_text())

    def test_confirm_sends_yes_and_pya_text_output(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 0, "Tarragona Ñuñoa: activado\n")
        r = self.client.post("/api/stores/activate", json={"platform": "pedidosya", "names": ["Ñuñoa"], "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("--yes", self.cli_args())
        self.assertNotIn("--dry-run", self.cli_args())
        self.assertIsNone(r.json()["results"])
        self.assertIn("activado", r.json()["output"])

    def test_confirm_must_be_literal_true(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 0, "[]")
        self.client.post("/api/stores/activate", json={"platform": "uber", "names": ["x"], "confirm": "true"})
        self.assertIn("--dry-run", self.cli_args())

    def test_validation_and_missing_session(self):
        self.login()
        r = self.client.post("/api/stores/pause", json={"platform": "uber", "names": ["x"], "duration": "45"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/stores/pause", json={"platform": "pedidosya", "names": ["x"], "reason": "NOPE"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/stores/activate", json={"platform": "uber"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/stores/activate", json={"platform": "uber", "names": ["x"]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.calls, [])

    def test_auth_failure_is_reported_not_zero(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 1, "", "HTTP 401 Unauthorized")
        r = self.client.post("/api/stores/activate", json={"platform": "uber", "names": ["x"]})
        self.assertEqual(r.status_code, 502)


class CatalogTests(ExtraBase):
    def test_soldout_report_and_item_writes(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 0, '[{"tienda": "A", "producto": "Pizza"}]')
        data = self.client.get("/api/catalog/soldout?platform=uber&store=Centro").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(self.cli_args()[:2], ["soldout-report", "--json"])
        r = self.client.post("/api/catalog/soldout", json={"platform": "pedidosya", "item": "Pizza", "match": "contains",
                                                            "until": "tomorrow"})
        self.assertEqual(r.status_code, 200, r.text)
        args = self.cli_args()
        self.assertIn("--dry-run", args)
        self.assertIn("--contains", args)
        self.assertEqual(args[args.index("--until") + 1], "tomorrow")
        r = self.client.post("/api/catalog/soldout", json={"platform": "uber", "item": "Pizza", "until": "tomorrow"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/catalog/instock", json={"platform": "uber", "item": ""})
        self.assertEqual(r.status_code, 400)

    def test_activate_menu_excludes(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 0, "[]")
        r = self.client.post("/api/catalog/activate-menu", json={"platform": "uber", "extra_excludes": ["Bebidas"], "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        args = self.cli_args()
        self.assertIn("--yes", args)
        self.assertIn("--json", args)
        self.assertEqual(args[args.index("--exclude") + 1], "Bebidas")


class ReportsTests(ExtraBase):
    def test_catalog_and_json_run_with_download(self):
        self.login()
        self.sessions()
        cat = self.client.get("/api/reports").json()["reports"]
        self.assertIn("pya_sales", [r["id"] for r in cat])
        self.handler = lambda cmd, env: completed(cmd, 0, '[{"dia": "2026-11-01", "total": 1000}]')
        job = self.client.post("/api/reports/run", json={"report": "pya_sales", "start": "2026-11-01",
                                                         "end": "2026-11-04"}).json()
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(self.cli_args()[:2], ["sales", "--json"])
        dl = self.client.get(job["download_url"])
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.json()[0]["total"], 1000)
        self.assertIn("no-store", dl.headers["cache-control"])
        self.assertEqual(self.client.get(f"/api/reports/jobs/{job['id']}").json()["status"], "done")

    def test_csv_vos_and_validation(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 0, "a,b\n1,2\n3,4\n")
        job = self.client.post("/api/reports/run", json={"report": "pya_vos_prep_time", "format": "csv"}).json()
        self.assertEqual(job["result_summary"], "2 filas CSV")
        self.assertEqual(self.cli_args()[:2], ["report", "prep_time"])
        self.assertEqual(self.client.post("/api/reports/run", json={"report": "pya_sales", "start": "ayer"}).status_code, 400)
        self.assertEqual(self.client.post("/api/reports/run", json={"report": "nope"}).status_code, 404)

    def test_stores_snapshot_export_is_public(self):
        self.login()
        self.write_snapshot({"generated_at": "2026-11-05T10:00:00-03:00", "stores": STORES})
        job = self.client.post("/api/reports/run", json={"report": "stores_snapshot"}).json()
        self.assertEqual(job["status"], "done", job)
        body = self.client.get(job["download_url"]).text
        self.assertNotIn("INTERNO-NO-SALE", body)
        self.assertEqual(self.calls, [])

    def test_cli_error_marks_job_error(self):
        self.login()
        self.sessions()
        self.handler = lambda cmd, env: completed(cmd, 1, "", "HTTP 403 Forbidden")
        r = self.client.post("/api/reports/run", json={"report": "uber_sales"})
        self.assertGreaterEqual(r.status_code, 400)


class AutomationsTests(ExtraBase):
    def test_create_run_toggle_delete(self):
        self.login()
        self.sessions()
        r = self.client.post("/api/automations", json={"name": "Ventas", "kind": "report", "schedule": "0 8 * * 1-5",
                                                        "payload": {"report": "pya_sales", "format": "csv"}})
        self.assertEqual(r.status_code, 200, r.text)
        auto = r.json()
        self.handler = lambda cmd, env: completed(cmd, 0, "a\n1\n")
        run = self.client.post(f"/api/automations/{auto['id']}/run").json()
        self.assertTrue(run["ok"], run)
        listed = self.client.get("/api/automations").json()["automations"][0]
        self.assertEqual(listed["last_status"], "ok")
        self.assertFalse(self.client.patch(f"/api/automations/{auto['id']}", json={"enabled": False}).json()["enabled"])
        self.assertTrue(self.client.delete(f"/api/automations/{auto['id']}").json()["deleted"])
        self.assertTrue((self.tmp / "data" / "automations.json").stat().st_mode & 0o077 == 0)

    def test_write_kinds_blocked_and_bad_cron(self):
        self.login()
        r = self.client.post("/api/automations", json={"name": "x", "kind": "stores_pause"})
        self.assertEqual(r.status_code, 403)
        with mock.patch.dict(os.environ, {"ALLOW_SCHEDULED_WRITES": "true"}):
            r = self.client.post("/api/automations", json={"name": "x", "kind": "stores_pause"})
            self.assertEqual(r.status_code, 501)
        r = self.client.post("/api/automations", json={"name": "x", "kind": "refresh_snapshot", "schedule": "61 * * * *"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/automations", json={"name": "x", "kind": "report"})
        self.assertEqual(r.status_code, 400)

    def test_refresh_snapshot_uses_locked_refresh(self):
        self.login()
        auto = self.client.post("/api/automations", json={"name": "r", "kind": "refresh_snapshot"}).json()
        with mock.patch("app.main._do_refresh", return_value={"available": True}) as fake:
            run = self.client.post(f"/api/automations/{auto['id']}/run").json()
        self.assertTrue(run["ok"])
        fake.assert_called_once()

    def test_cron_matching_and_due(self):
        when = dt.datetime(2026, 11, 2, 8, 0, tzinfo=automations.TZ)
        self.assertTrue(automations.cron_matches("0 8 * * 1-5", when))
        self.assertFalse(automations.cron_matches("0 8 * * 0,6", when))
        self.assertTrue(automations.cron_matches("*/15 * * * *", when))
        self.assertFalse(automations.cron_matches("30 8 * * *", when))
        self.login()
        self.client.post("/api/automations", json={"name": "r", "kind": "refresh_snapshot", "schedule": "0 8 * * *"})
        self.assertEqual(len(automations.due(when)), 1)
        self.assertEqual(automations.due(when.replace(minute=1)), [])


class AgentsTests(ExtraBase):
    def create(self, scopes):
        r = self.client.post("/api/agents", json={"name": "bot", "scopes": scopes})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_key_shown_once_and_only_hash_stored(self):
        self.login()
        data = self.create(["snapshot.read"])
        key = data["api_key"]
        self.assertTrue(key.startswith("tdk_"))
        listing = self.client.get("/api/agents").text
        self.assertNotIn(key, listing)
        self.assertNotIn("key_hash", listing)
        stored = (self.tmp / "data" / "agents.json").read_text()
        self.assertNotIn(key, stored)
        self.assertEqual((self.tmp / "data" / "agents.json").stat().st_mode & 0o077, 0)
        self.assertNotIn(key, self.audit_text())

    def test_human_only_scopes_rejected(self):
        self.login()
        for scope in ("credentials.write", "agents.admin"):
            r = self.client.post("/api/agents", json={"name": "bot", "scopes": [scope]})
            self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post("/api/agents", json={"name": "bot", "scopes": ["root"]}).status_code, 400)

    def test_bearer_auth_respects_scopes_and_revocation(self):
        self.login()
        data = self.create(["snapshot.read"])
        key = data["api_key"]
        self.client.cookies.clear()
        bearer = {"Authorization": f"Bearer {key}"}
        self.write_snapshot({"stores": STORES})
        self.assertEqual(self.client.get("/api/stores", headers=bearer).status_code, 200)
        self.assertEqual(self.client.get("/api/snapshot", headers=bearer).status_code, 200)
        self.assertEqual(self.client.post("/api/stores/activate", headers=bearer, json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/credentials/status", headers=bearer).status_code, 403)
        self.assertEqual(self.client.get("/api/agents", headers=bearer).status_code, 403)
        self.assertEqual(self.client.get("/api/stores", headers={"Authorization": "Bearer tdk_falsa"}).status_code, 401)
        self.login()
        self.client.delete(f"/api/agents/{data['id']}")
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/stores", headers=bearer).status_code, 401)

    def test_agent_rate_limit(self):
        self.login()
        key = self.create(["snapshot.read"])["api_key"]
        self.client.cookies.clear()
        with mock.patch.object(agents, "RATE_LIMIT", 3):
            codes = [self.client.get("/api/stores", headers={"Authorization": f"Bearer {key}"}).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])


if __name__ == "__main__":
    import unittest

    unittest.main()
