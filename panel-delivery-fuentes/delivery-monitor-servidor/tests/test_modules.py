import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app import auth, deps
from app.main import app
from app.modules import credentials, evidence

USER = "qa-modulos"
PASSWORD = "clave-de-prueba-modulos-123"
EVID_KEY = "EVIDENCIA-KEY-NO-DEBE-SALIR-987"
COOKIE_SECRET = "sid=COOKIE-SECRETA-UBER-555; csid=OTRA-PARTE-777"
EVID_URL = "https://proyecto.supabase.co/functions/v1/evidencia"
_RealClient = httpx.Client


def completed(cmd, rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, rc, stdout, stderr)


class ModulesBase(unittest.TestCase):
    evidencia_key = ""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dm-mod-"))
        for name in ("data", "media", "sessions", "home"):
            (self.tmp / name).mkdir()
        env = {
            "PANEL_USER": USER,
            "PANEL_PASSWORD": PASSWORD,
            "SESSION_SECRET": "session-secret-modulos-1234567890",
            "SESSION_SECURE": "false",
            "SNAPSHOT_PATH": str(self.tmp / "data" / "snapshot.json"),
            "MEDIA_DIR": str(self.tmp / "media"),
            "SESSIONS_DIR": str(self.tmp / "sessions"),
            "CLI_HOME": str(self.tmp / "home"),
            "REFRESH_INTERVAL_MINUTES": "0",
            "EVIDENCIA_URL": EVID_URL,
            "EVIDENCIA_API_KEY": self.evidencia_key,
            "ALLOW_UBER_DISPUTE_SUBMIT": "",
            "UBER_COOKIE": "",
            "UBER_CLI": "/opt/fake/uber.py",
            "UBER_CLI_CWD": str(self.tmp),
            "PYA_CLI": "/opt/fake/pya.py",
            "PYA_CLI_CWD": str(self.tmp),
        }
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        deps.reset_settings()
        credentials._cache.clear()
        evidence._cache.clear()
        auth._login_hits.clear()
        self.calls = []
        self.handler = lambda cmd, env: completed(cmd, 1, "", "sin mock")
        self.run_patch = mock.patch("delivery_monitor.adapters.runner.subprocess.run", side_effect=self._fake_run)
        self.run_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.run_patch.stop()
        self.env.stop()
        deps.reset_settings()
        credentials._cache.clear()
        evidence._cache.clear()

    def _fake_run(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), "env": kwargs.get("env") or {}})
        return self.handler(list(cmd), kwargs.get("env") or {})

    def login(self):
        r = self.client.post("/api/login", data={"username": USER, "password": PASSWORD})
        self.assertEqual(r.status_code, 200)

    def write_session(self, source, content):
        name = credentials.SOURCES[source]["file"]
        (self.tmp / "sessions" / name).write_text(content, encoding="utf-8")

    def write_snapshot(self, data):
        (self.tmp / "data" / "snapshot.json").write_text(json.dumps(data), encoding="utf-8")

    def audit_text(self):
        path = self.tmp / "data" / "acciones.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""


class AuthOnNewRoutesTests(ModulesBase):
    ROUTES = [
        ("get", "/api/credentials/status"),
        ("put", "/api/credentials/uber"),
        ("put", "/api/credentials/pedidosya"),
        ("put", "/api/credentials/rappi"),
        ("delete", "/api/credentials/uber"),
        ("get", "/api/disputes?platform=uber"),
        ("get", "/api/disputes?platform=pedidosya"),
        ("get", "/api/disputes/uber/AA7A2"),
        ("post", "/api/disputes/uber/AA7A2/submit"),
        ("post", "/api/disputes/pedidosya/123/submit"),
        ("get", "/api/orders/pedidosya/123?store_id=PY_CL;1"),
        ("get", "/api/disputes/uber/AA7A2/media/abcdefgh12.jpg"),
        ("get", "/api/orders/pedidosya/123/media/abcdefgh12.jpg"),
        ("patch", "/api/media/uber/AA7A2/abcdefgh12.jpg"),
        ("get", "/api/evidence/uber?numero_orden=AA7A2"),
        ("get", "/api/evidence/uber/media/img1?numero_orden=AA7A2"),
    ]

    def test_every_new_route_requires_session(self):
        for method, path in self.ROUTES:
            with self.subTest(route=f"{method.upper()} {path}"):
                kwargs = {"json": {}} if method in ("post", "patch") else {}
                r = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(r.status_code, 401, r.text)
        self.assertEqual(self.calls, [])


class UberDisputeTests(ModulesBase):
    def setUp(self):
        super().setUp()
        self.login()
        self.write_session("uber", COOKIE_SECRET)
        self.write_snapshot({
            "stores": [{"platform": "uber", "store_id": "rest-uuid-1", "name": "Tarragona - Centro"}],
            "disputes": [{"platform": "uber", "order_id": "AA7A2", "store_name": "Tarragona - Centro",
                          "workflow_uuid": "wf-uuid-1", "amount_clp": 7990}],
            "sources": {"uber": {"disputes_status": "ok", "fetched_at": "2026-11-05 10:00"}},
        })

    def plan_handler(self, cmd, env):
        self.assertEqual(cmd[1], "/opt/fake/uber.py")
        plan = {"order": "AA7A2", "store": "Tarragona - Centro", "eligibility": {"eligible": True},
                "problems": [], "transport": "graphql", "evidence_files": [],
                "variables": {"disputeSubmission": {"reason": "OTHER"}}}
        return completed(cmd, 0, json.dumps(plan), "")

    def test_dry_run_never_passes_yes(self):
        self.handler = self.plan_handler
        r = self.client.post("/api/disputes/uber/AA7A2/submit",
                             json={"reason": "OTHER", "description": "Pedido entregado completo"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["verified"])
        self.assertEqual(len(self.calls), 1)
        cmd = self.calls[0]["cmd"]
        self.assertIn("--dry-run", cmd)
        self.assertNotIn("--yes", cmd)
        self.assertEqual(cmd[cmd.index("--workflow") + 1], "wf-uuid-1")
        self.assertEqual(cmd[cmd.index("--restaurant") + 1], "rest-uuid-1")
        self.assertIn('"dry_run": true', self.audit_text())

    def test_confirm_without_flag_is_403_and_runs_nothing(self):
        r = self.client.post("/api/disputes/uber/AA7A2/submit",
                             json={"reason": "OTHER", "description": "x", "confirm": True})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.calls, [])
        self.assertIn("bloqueado", self.audit_text())

    def test_confirm_with_flag_passes_yes_and_stays_unverified(self):
        os.environ["ALLOW_UBER_DISPUTE_SUBMIT"] = "true"
        self.handler = lambda cmd, env: completed(cmd, 0, '{"ok": true}', "")
        r = self.client.post("/api/disputes/uber/AA7A2/submit",
                             json={"reason": "STORE_EVIDENCE_AVAILABLE", "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["verified"])
        self.assertIn("--yes", self.calls[0]["cmd"])
        self.assertNotIn("--dry-run", self.calls[0]["cmd"])

    def test_more_than_three_evidences_rejected(self):
        r = self.client.post("/api/disputes/uber/AA7A2/submit",
                             json={"reason": "OTHER", "description": "x", "evidence_ids": ["a", "b"], "app_evidence_ids": ["c", "d"]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_auth_failure_is_error_not_zero(self):
        self.handler = lambda cmd, env: completed(cmd, 1, "", "HTTP 401 Unauthorized: sesión caducada")
        r = self.client.get("/api/disputes?platform=uber&live=true")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "error")
        self.assertTrue(body["auth"])
        self.assertIsNone(body["disputes"])
        self.assertNotIn("COOKIE-SECRETA", r.text)

    def test_live_list_without_session_does_not_call_uber(self):
        (self.tmp / "sessions" / "uber_cookie").unlink()
        r = self.client.get("/api/disputes?platform=uber&live=true")
        body = r.json()
        self.assertEqual(body["status"], "missing_credentials")
        self.assertIsNone(body["disputes"])
        self.assertEqual(self.calls, [])

    def test_live_list_ok_and_child_env_has_no_panel_secrets(self):
        os.environ["EVIDENCIA_API_KEY"] = EVID_KEY
        rows = [{"order": "BB123", "store": "Tarragona - Centro", "workflow": "wf-2", "amount": "$5.990"}]
        self.handler = lambda cmd, env: completed(cmd, 0, json.dumps(rows), "")
        r = self.client.get("/api/disputes?platform=uber&live=true&start=2026-10-06&end=2026-11-05")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(len(body["disputes"]), 1)
        self.assertNotIn("workflow_uuid", body["disputes"][0])
        env = self.calls[0]["env"]
        self.assertNotIn("PANEL_PASSWORD", env)
        self.assertNotIn("SESSION_SECRET", env)
        self.assertNotIn("EVIDENCIA_API_KEY", env)
        self.assertEqual(env.get("HOME"), str(self.tmp / "home"))

    def test_snapshot_list_without_snapshot_is_pending(self):
        (self.tmp / "data" / "snapshot.json").unlink()
        body = self.client.get("/api/disputes?platform=uber").json()
        self.assertEqual(body["status"], "pending")
        self.assertIsNone(body["disputes"])

    def test_detail_downloads_and_serves_photos_with_session_only(self):
        def handler(cmd, env):
            out = Path(cmd[cmd.index("--out") + 1])
            folder = out / "AA7A2"
            (folder / "cliente").mkdir(parents=True)
            (folder / "tienda").mkdir()
            (folder / "cliente" / "foto-original-cliente.jpg").write_bytes(b"\xff\xd8cliente")
            (folder / "tienda" / "evidencia.png").write_bytes(b"\x89PNGtienda")
            (folder / "detalle.json").write_text(json.dumps({"files": [{"path": "x"}]}), encoding="utf-8")
            rows = [{"order": "AA7A2", "store": "Tarragona - Centro", "comentario_cliente": "faltó bebida"}]
            return completed(cmd, 0, json.dumps(rows), "")
        self.handler = handler
        r = self.client.get("/api/disputes/uber/AA7A2")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["platform_fetch"]["status"], "ok")
        groups = sorted(m["group"] for m in body["platform_media"])
        self.assertEqual(groups, ["cliente", "tienda"])
        self.assertTrue(body["submit"]["can_prepare"])
        self.assertFalse(body["submit"]["verified_live"])
        self.assertEqual(body["app_evidence"]["status"], "not_configured")
        self.assertNotIn("foto-original-cliente", r.text)
        self.assertFalse(any(p.name == "detalle.json" for p in (self.tmp / "media").rglob("*")))

        media_url = next(m["url"] for m in body["platform_media"] if m["group"] == "cliente")
        img = self.client.get(media_url)
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.content, b"\xff\xd8cliente")
        self.assertIn("private", img.headers["cache-control"])

        mid = media_url.rsplit("/", 1)[1]
        r = self.client.patch(f"/api/media/uber/AA7A2/{mid}", json={"sensitive": True})
        self.assertTrue(r.json()["item"]["sensitive"])

        anon = TestClient(app)
        self.assertEqual(anon.get(media_url).status_code, 401)

        cached = self.client.get("/api/disputes/uber/AA7A2").json()
        self.assertEqual(cached["platform_fetch"]["status"], "cached")
        self.assertTrue(next(m for m in cached["platform_media"] if m["id"] == mid)["sensitive"])
        self.assertEqual(len(self.calls), 1)

    def test_bad_order_id_rejected(self):
        r = self.client.get("/api/disputes/uber/..%2Fetc")
        self.assertIn(r.status_code, (400, 404))
        self.assertEqual(self.calls, [])


class PedidosYaTests(ModulesBase):
    def setUp(self):
        super().setUp()
        self.login()
        self.write_session("pedidosya", json.dumps({"access": "ACCESS-PYA-SECRET", "refresh": "REFRESH-PYA"}))

    def test_issues_are_not_disputes(self):
        tiles = [{"type": "MISSING_ITEM", "orders": 3, "amount": 4500, "store": "Tarragona - Sur"}]
        self.handler = lambda cmd, env: completed(cmd, 0, json.dumps(tiles), "")
        body = self.client.get("/api/disputes?platform=pedidosya&live=true").json()
        self.assertEqual(body["disputes_status"], "no_direct_list")
        self.assertIsNone(body["disputes"])
        self.assertEqual(len(body["complaint_tiles"]), 1)
        self.assertIn("issues", self.calls[0]["cmd"])

    def test_issues_auth_failure_is_not_zero(self):
        self.handler = lambda cmd, env: completed(cmd, 1, "", "403 Forbidden")
        body = self.client.get("/api/disputes?platform=pedidosya&live=true").json()
        self.assertEqual(body["status"], "error")
        self.assertTrue(body["auth"])
        self.assertIsNone(body["complaint_tiles"])

    def test_submit_is_501(self):
        r = self.client.post("/api/disputes/pedidosya/2355819567/submit", json={"confirm": True})
        self.assertEqual(r.status_code, 501)
        self.assertEqual(self.calls, [])

    def test_order_requires_store(self):
        r = self.client.get("/api/orders/pedidosya/2355819567")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_order_with_photos_hides_customer_data(self):
        raw = {
            "order": {
                "order": {"orderId": "2355819567", "status": "DELIVERED", "vendorName": "Tarragona - Sur",
                          "orderValue": "12990", "items": [{"name": "Pizza", "quantity": 1}],
                          "deliveryLocation": {"street": "Calle Privada 123"}, "customerNotes": "Depto 4B"},
                "orderIssues": [{"orderIssue": "MISSING_ITEM", "metadata": {"reason": "falta", "amount": 3000}}],
                "isDisputeAllowed": True,
            },
            "orderIssuePictures": {"urls": ["[url redactada]"], "files": [{"index": 1, "file": "01.jpg"}]},
        }

        def handler(cmd, env):
            out = Path(cmd[cmd.index("--download") + 1])
            (out / "01.jpg").write_bytes(b"\xff\xd8reclamo")
            self.assertEqual(cmd[cmd.index("--id") + 1], "PY_CL;616753")
            return completed(cmd, 0, json.dumps(raw), "")
        self.handler = handler
        r = self.client.get("/api/orders/pedidosya/2355819567?store_id=PY_CL;616753&photos=true")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["order"]["vendor_name"], "Tarragona - Sur")
        self.assertEqual(body["pictures"]["downloaded"], 1)
        self.assertEqual(len(body["platform_media"]), 1)
        self.assertFalse(body["dispute_submit"]["available"])
        self.assertNotIn("Calle Privada", r.text)
        self.assertNotIn("Depto 4B", r.text)
        self.assertNotIn("ACCESS-PYA-SECRET", r.text)
        img = self.client.get(body["platform_media"][0]["url"])
        self.assertEqual(img.content, b"\xff\xd8reclamo")


class RappiTests(ModulesBase):
    def test_rappi_is_pending_and_501(self):
        self.login()
        self.assertEqual(self.client.put("/api/credentials/rappi").status_code, 501)
        self.assertEqual(self.client.delete("/api/credentials/rappi?confirm=true").status_code, 501)
        body = self.client.get("/api/disputes?platform=rappi").json()
        self.assertEqual(body["status"], "pending")
        self.assertIsNone(body["disputes"])


class CredentialsTests(ModulesBase):
    def setUp(self):
        super().setUp()
        self.login()

    def probe_ok(self, cmd, env):
        self.assertEqual(cmd[1], "-c")
        cookie = Path(env["HOME"]) / ".uber_cookie"
        if cookie.exists() and "COOKIE-SECRETA" in cookie.read_text():
            return completed(cmd, 0, '{"stores": 12}', "")
        return completed(cmd, 1, "", "HTTP 401 Unauthorized")

    def test_status_without_sessions(self):
        body = self.client.get("/api/credentials/status").json()
        by = {s["source"]: s for s in body["sources"]}
        self.assertEqual(by["uber"]["status"], "missing")
        self.assertEqual(by["pedidosya"]["status"], "missing")
        self.assertEqual(by["rappi"]["status"], "pending")
        self.assertEqual(by["evidencia"]["status"], "missing")
        self.assertEqual(self.calls, [])

    def test_put_uber_installs_and_never_echoes_value(self):
        self.handler = self.probe_ok
        r = self.client.put("/api/credentials/uber", data={"value": "Cookie: " + COOKIE_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        self.assertNotIn("COOKIE-SECRETA", r.text)
        self.assertNotIn("OTRA-PARTE", r.text)
        stored = self.tmp / "sessions" / "uber_cookie"
        self.assertEqual(stored.read_text(), COOKIE_SECRET)
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.tmp / "home" / ".uber_cookie").is_symlink())
        self.assertNotEqual(self.calls[0]["env"]["HOME"], str(self.tmp / "home"))

        status = self.client.get("/api/credentials/status")
        self.assertNotIn("COOKIE-SECRETA", status.text)
        by = {s["source"]: s for s in status.json()["sources"]}
        self.assertEqual(by["uber"]["status"], "configured")
        self.assertNotIn("COOKIE-SECRETA", self.audit_text())

    def test_failed_probe_keeps_previous_session(self):
        self.write_session("uber", "sid=ANTERIOR-VIGENTE")
        self.handler = self.probe_ok
        r = self.client.put("/api/credentials/uber", data={"value": "sid=MALA-CADUCADA"})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("MALA-CADUCADA", r.text)
        self.assertEqual((self.tmp / "sessions" / "uber_cookie").read_text(), "sid=ANTERIOR-VIGENTE")
        self.assertFalse((self.tmp / "sessions" / "uber_cookie.tmp").exists())

    def test_put_pedidosya_file_validates_json(self):
        r = self.client.put("/api/credentials/pedidosya", files={"file": ("pya_tokens.json", b"no-es-json", "application/json")})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_put_pedidosya_expired_shows_otp_hint(self):
        self.handler = lambda cmd, env: completed(cmd, 1, "", "RuntimeError: OTP_REQUIRED Login failed")
        r = self.client.put("/api/credentials/pedidosya",
                            files={"file": ("pya_tokens.json", json.dumps({"access": "A-SECRET", "refresh": "R-SECRET"}).encode(), "application/json")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("OTP", r.json()["detail"])
        self.assertNotIn("A-SECRET", r.text)
        self.assertFalse((self.tmp / "sessions" / "pya_tokens.json").exists())

    def test_delete_is_dry_run_first(self):
        self.write_session("uber", COOKIE_SECRET)
        plan = self.client.delete("/api/credentials/uber").json()
        self.assertTrue(plan["dry_run"])
        self.assertTrue(plan["results"][0]["would_delete"])
        self.assertTrue((self.tmp / "sessions" / "uber_cookie").exists())
        done = self.client.delete("/api/credentials/uber?confirm=true").json()
        self.assertTrue(done["results"][0]["deleted"])
        self.assertFalse((self.tmp / "sessions" / "uber_cookie").exists())

    def test_status_probe_auth_failure_is_expired(self):
        self.write_session("uber", "sid=VIEJA")
        self.handler = lambda cmd, env: completed(cmd, 1, "", "HTTP 401 Unauthorized")
        body = self.client.get("/api/credentials/status?check=true").json()
        by = {s["source"]: s for s in body["sources"]}
        self.assertEqual(by["uber"]["status"], "expired")


class EvidenceTests(ModulesBase):
    evidencia_key = EVID_KEY

    def setUp(self):
        super().setUp()
        self.login()
        self.requests = []

        def handler(request: httpx.Request):
            self.requests.append(request)
            if request.url.host == "proyecto.supabase.co" and request.url.path.endswith("/evidencia"):
                if request.headers.get("x-evidencia-key") != EVID_KEY:
                    return httpx.Response(401, json={"error": "unauthorized"})
                if request.url.params.get("numero_orden") == "VACIO":
                    return httpx.Response(200, json={"images": []})
                return httpx.Response(200, json={"images": [
                    {"id": "img-1", "created_at": "2026-11-05T12:00:00Z",
                     "url": "https://proyecto.supabase.co/storage/v1/object/sign/evidencia/a.jpg?token=FIRMA-SECRETA"},
                    {"id": "img-2", "created_at": "2026-11-05T12:01:00Z",
                     "url": "https://otro-host.example/a.jpg?token=X"},
                ]})
            if request.url.path.startswith("/storage/"):
                return httpx.Response(200, content=b"\xff\xd8app", headers={"content-type": "image/jpeg"})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        self.http_patch = mock.patch("app.modules.evidence.httpx.Client",
                                     side_effect=lambda **kw: _RealClient(transport=transport))
        self.http_patch.start()

    def tearDown(self):
        self.http_patch.stop()
        super().tearDown()

    def test_list_hides_key_and_signed_urls(self):
        r = self.client.get("/api/evidence/uber?numero_orden=AA7A2")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual([i["id"] for i in body["images"]], ["img-1"])
        self.assertTrue(body["images"][0]["url"].startswith("/api/evidence/uber/media/img-1?numero_orden=AA7A2"))
        self.assertNotIn(EVID_KEY, r.text)
        self.assertNotIn("FIRMA-SECRETA", r.text)
        self.assertNotIn("supabase.co", r.text)
        self.assertEqual(self.requests[0].url.params.get("agregador"), "uber")

    def test_proxy_serves_image(self):
        self.client.get("/api/evidence/uber?numero_orden=AA7A2")
        img = self.client.get("/api/evidence/uber/media/img-1?numero_orden=AA7A2")
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.content, b"\xff\xd8app")
        missing = self.client.get("/api/evidence/uber/media/img-2?numero_orden=AA7A2")
        self.assertEqual(missing.status_code, 404)
        self.assertFalse(any(r.url.host == "otro-host.example" for r in self.requests))

    def test_rejected_key_is_error_not_empty(self):
        os.environ["EVIDENCIA_API_KEY"] = "clave-mala"
        deps.reset_settings()
        body = self.client.get("/api/evidence/pedidosya?numero_orden=123").json()
        self.assertEqual(body["status"], "error")
        self.assertTrue(body["auth"])
        self.assertIsNone(body["images"])
        self.assertNotIn("clave-mala", json.dumps(body))

    def test_invalid_aggregator(self):
        r = self.client.get("/api/evidence/rappi?numero_orden=1")
        self.assertEqual(r.status_code, 400)

    def test_status_reports_evidence_configured(self):
        body = self.client.get("/api/credentials/status?check=true")
        by = {s["source"]: s for s in body.json()["sources"]}
        self.assertEqual(by["evidencia"]["status"], "configured")
        self.assertNotIn(EVID_KEY, body.text)


if __name__ == "__main__":
    unittest.main()
