import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.config import SettingsError, load_settings


def _base_env(**extra):
    env = {
        "PANEL_USER": "operador",
        "PANEL_PASSWORD": "clave-de-prueba-segura",
        "SESSION_SECRET": "abcdefghijklmnopqrstuvwxyz012345",
        "SESSION_SECURE": "false",
        "SNAPSHOT_PATH": "/tmp/snap.json",
        "REFRESH_INTERVAL_MINUTES": "0",
    }
    env.update(extra)
    return env


class ConfigTests(unittest.TestCase):
    def test_ok(self):
        with mock.patch.dict(os.environ, _base_env(), clear=False):
            s = load_settings()
        self.assertEqual(s.panel_user, "operador")
        self.assertEqual(s.refresh_interval_minutes, 0)

    def test_rejects_missing_user(self):
        with mock.patch.dict(os.environ, _base_env(PANEL_USER=""), clear=False):
            with self.assertRaises(SettingsError):
                load_settings()

    def test_rejects_defaultish_password(self):
        with mock.patch.dict(os.environ, _base_env(PANEL_PASSWORD="changeme"), clear=False):
            with self.assertRaises(SettingsError):
                load_settings()

    def test_rejects_short_password(self):
        with mock.patch.dict(os.environ, _base_env(PANEL_PASSWORD="corto"), clear=False):
            with self.assertRaises(SettingsError):
                load_settings()

    def test_rejects_short_secret(self):
        with mock.patch.dict(os.environ, _base_env(SESSION_SECRET="demasiado-corto"), clear=False):
            with self.assertRaises(SettingsError):
                load_settings()

    def test_interval_minimum(self):
        with mock.patch.dict(os.environ, _base_env(REFRESH_INTERVAL_MINUTES="5"), clear=False):
            with self.assertRaises(SettingsError):
                load_settings()

    def test_password_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pw"
            path.write_text("clave-desde-archivo-xyz\n", encoding="utf-8")
            env = _base_env(PANEL_PASSWORD_FILE=str(path))
            env["PANEL_PASSWORD"] = ""
            with mock.patch.dict(os.environ, env, clear=False):
                s = load_settings()
            self.assertEqual(s.panel_password, "clave-desde-archivo-xyz")
