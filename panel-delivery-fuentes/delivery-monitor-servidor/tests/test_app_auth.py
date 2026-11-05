import json
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="dm-panel-")
_SNAP = str(Path(_TMP) / "snapshot.json")

os.environ["PANEL_USER"] = "paneltester"
os.environ["PANEL_PASSWORD"] = "unic-clave-segura-xyz"
os.environ["SESSION_SECRET"] = "session-secret-para-pruebas-1234567890"
os.environ["SESSION_SECURE"] = "false"
os.environ["SNAPSHOT_PATH"] = _SNAP
os.environ["REFRESH_INTERVAL_MINUTES"] = "0"
os.environ["TZ"] = "America/Santiago"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, public_snapshot  # noqa: E402
from delivery_monitor.adapters.runner import _child_env  # noqa: E402


class PanelAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_healthz_public(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_snapshot_requires_auth(self):
        r = self.client.get("/api/snapshot")
        self.assertEqual(r.status_code, 401)

    def test_health_requires_auth(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 401)

    def test_refresh_requires_auth(self):
        r = self.client.post("/api/refresh")
        self.assertEqual(r.status_code, 401)

    def test_bad_login(self):
        r = self.client.post("/api/login", data={"username": "paneltester", "password": "no-es-la-clave-xxx"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("unic-clave-segura-xyz", r.text)

    def test_login_and_empty_snapshot_is_pending_not_zero(self):
        if Path(_SNAP).exists():
            Path(_SNAP).unlink()
        r = self.client.post("/api/login", data={"username": "paneltester", "password": "unic-clave-segura-xyz"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.cookies.get("dm_session"))
        snap = self.client.get("/api/snapshot")
        self.assertEqual(snap.status_code, 200)
        body = snap.json()
        self.assertFalse(body["available"])
        self.assertIsNone(body["totals"])
        self.assertEqual(body["stores"], [])
        self.assertEqual(body["disputes"], [])
        for name, src in body["sources"].items():
            self.assertIsNone(src["stores_count"], msg=name)
            self.assertNotEqual(src["stores_count"], 0)
            self.assertIn(src["status"], ("pending", "error"))
        self.assertNotIn("unic-clave-segura-xyz", snap.text)
        self.assertNotIn("session-secret-para-pruebas", snap.text)

    def test_public_snapshot_strips_workflow_uuid(self):
        snap = {
            "generated_at": "2026-11-05T16:40:40-03:00",
            "timezone": "America/Santiago",
            "sources": {
                "uber": {
                    "status": "ok",
                    "fetched_at": "2026-11-05T16:39:29-03:00",
                    "error": None,
                    "stores_count": 1,
                    "disputes_status": "ok",
                    "disputes_count": 1,
                }
            },
            "totals": {"stores": 1, "open_now": 1, "disputes_unopened": 1},
            "stores": [{
                "platform": "uber", "store_id": "abc", "name": "Tarragona - Prueba",
                "brand": "Tarragona", "status": "abierta", "status_raw": "open",
                "open_now": True, "enabled": True, "reason": "", "since": None,
                "until": None, "next_open": None, "next_close": None, "slot": None,
                "excluded": False, "author": None,
            }],
            "disputes": [{
                "platform": "uber", "store_name": "Tarragona - Prueba", "brand": "Tarragona",
                "order_id": "AB12C", "workflow_uuid": "no-debe-salir",
                "ordered_at": "2026-11-01 12:00", "amount_clp": 1990,
                "amount_display": "$1.990", "issue": "ISSUE_WITH_ITEMS",
                "tag": "ISSUE_CHARGED", "state": "pendiente", "eligibility": None,
                "window_start": "2026-10-07", "window_end": "2026-11-05",
            }],
            "complaint_tiles": [],
            "status_labels": {"abierta": "Abierta"},
        }
        out = public_snapshot(snap)
        self.assertTrue(out["available"])
        self.assertEqual(out["disputes"][0]["order_id"], "AB12C")
        self.assertNotIn("workflow_uuid", out["disputes"][0])
        dumped = json.dumps(out)
        self.assertNotIn("no-debe-salir", dumped)

    def test_child_env_drops_panel_secrets(self):
        os.environ["PANEL_PASSWORD"] = "unic-clave-segura-xyz"
        os.environ["SESSION_SECRET"] = "session-secret-para-pruebas-1234567890"
        env = _child_env()
        self.assertNotIn("PANEL_PASSWORD", env)
        self.assertNotIn("PANEL_USER", env)
        self.assertNotIn("SESSION_SECRET", env)

    def test_no_star_cors_header(self):
        r = self.client.get("/healthz")
        acao = r.headers.get("access-control-allow-origin")
        self.assertTrue(acao is None or acao != "*")

    def test_index_redirects_without_session(self):
        fresh = TestClient(app)
        r = fresh.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers.get("location"), "/login")
