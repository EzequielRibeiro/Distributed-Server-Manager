#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
WEB = DASHBOARD / "web"

import sys
sys.path.insert(0, str(DASHBOARD))

import controller_session
from login_credentials import authenticate_login_credentials


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class BrowserSessionSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        controller_session.SESSION_FILE = Path(self.tempdir.name) / "sessions.json"
        controller_session._sessions.clear()
        controller_session._loaded = False

    def tearDown(self):
        controller_session._sessions.clear()
        controller_session._loaded = False
        self.tempdir.cleanup()

    def test_controller_login_rejects_customer_identity(self):
        result = authenticate_login_credentials(
            Headers(),
            controller_authenticator=lambda _: {
                "username": "customer@example.test",
                "role": "customer",
                "scope_id": "cli-1",
            },
            customer_authenticator=lambda _: {
                "username": "customer@example.test",
                "role": "customer",
            },
        )
        self.assertIsNone(result)

    def test_session_survives_registry_reload_without_storing_raw_token(self):
        user = {"username": "admin", "role": "admin", "scope_id": "controller"}
        token = controller_session.create_session(user)
        persisted = controller_session.SESSION_FILE.read_text(encoding="utf-8")
        self.assertNotIn(token, persisted)

        controller_session._sessions.clear()
        controller_session._loaded = False
        restored = controller_session.get_session(token)
        self.assertEqual(restored["username"], "admin")
        self.assertEqual(restored["role"], "admin")

    def test_cookie_is_persistent_httponly_strict_and_secure_under_https(self):
        token = controller_session.create_session({"username": "admin", "role": "admin"})
        with patch.dict(os.environ, {"DSM_WEB_SCHEME": "https"}, clear=False):
            header = controller_session.cookie_header(token)
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Strict", header)
        self.assertIn("Secure", header)
        self.assertIn("Max-Age=", header)
        self.assertIn("Expires=", header)

    def test_logout_revokes_persisted_session(self):
        token = controller_session.create_session({"username": "admin", "role": "admin"})
        self.assertIsNotNone(controller_session.get_session(token))
        controller_session.revoke_session(token)
        self.assertIsNone(controller_session.get_session(token))

    def test_browser_bridge_never_contains_a_password_derived_basic_value(self):
        bridge = (WEB / "browser-session-bridge.js").read_text(encoding="utf-8")
        self.assertIn('COMPAT_VALUE = "cookie-session"', bridge)
        self.assertIn('headers.delete("Authorization")', bridge)
        self.assertNotIn("btoa(", bridge)
        self.assertIn("/api/auth/logout", bridge)

    def test_login_frontends_do_not_persist_basic_credentials(self):
        admin = (WEB / "auth.js").read_text(encoding="utf-8")
        customer = (WEB / "customer-auth.js").read_text(encoding="utf-8")
        self.assertNotIn('sessionStorage.setItem("dsm_auth"', admin)
        self.assertNotIn('sessionStorage.setItem("dsm_auth"', customer)
        self.assertIn('/api/customer/auth/session', customer)
        self.assertIn('/api/auth/login', admin)

    def test_final_composition_installs_browser_session_boundary(self):
        source = (DASHBOARD / "server_part17.py").read_text(encoding="utf-8")
        self.assertIn("install_browser_session_http", source)
        self.assertIn("browser_login_base.credential_authenticate", source)


if __name__ == "__main__":
    unittest.main()
