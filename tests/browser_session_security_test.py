#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
WEB = DASHBOARD / "web"
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

    def test_customer_session_preserves_canonical_identity(self):
        user = {
            "username": "aurora",
            "role": "customer",
            "customer_id": 1,
            "customer_code": "CLI-000001",
            "scope_id": 1,
        }
        token = controller_session.create_session(user)
        restored = controller_session.get_session(token)
        self.assertIsNotNone(restored)
        self.assertEqual(restored["username"], "aurora")
        self.assertEqual(restored["role"], "customer")
        self.assertEqual(restored["customer_id"], 1)
        self.assertEqual(restored["customer_code"], "CLI-000001")
        self.assertEqual(restored["scope_id"], 1)

    def test_customer_identity_survives_cookie_header_reconstruction(self):
        token = controller_session.create_session(
            {
                "username": "aurora",
                "role": "customer",
                "customer_id": 1,
                "customer_code": "CLI-000001",
                "scope_id": 1,
            }
        )
        restored = controller_session.session_user_from_headers(
            Headers({"Cookie": f"{controller_session.CUSTOMER_SESSION_COOKIE}={token}"}),
            area="customer",
        )
        self.assertIsNotNone(restored)
        self.assertEqual(restored["username"], "aurora")
        self.assertEqual(restored["role"], "customer")
        self.assertEqual(restored["customer_id"], 1)
        self.assertEqual(restored["customer_code"], "CLI-000001")
        self.assertEqual(restored["scope_id"], 1)

    def test_controller_and_customer_sessions_coexist_in_same_cookie_header(self):
        controller_token = controller_session.create_session(
            {"username": "admin", "role": "admin", "scope_id": "controller"}
        )
        customer_token = controller_session.create_session(
            {
                "username": "aurora",
                "role": "customer",
                "scope_id": 1,
                "customer_id": 1,
                "customer_code": "CLI-000001",
            }
        )
        headers = Headers(
            {
                "Cookie": (
                    f"{controller_session.CONTROLLER_SESSION_COOKIE}={controller_token}; "
                    f"{controller_session.CUSTOMER_SESSION_COOKIE}={customer_token}"
                )
            }
        )
        controller = controller_session.session_user_from_headers(headers, area="controller")
        customer = controller_session.session_user_from_headers(headers, area="customer")
        self.assertEqual(controller["username"], "admin")
        self.assertEqual(controller["role"], "admin")
        self.assertEqual(customer["username"], "aurora")
        self.assertEqual(customer["role"], "customer")
        self.assertEqual(customer["customer_id"], 1)

    def test_area_cookie_headers_have_distinct_names(self):
        controller_token = controller_session.create_session(
            {"username": "admin", "role": "admin"}
        )
        customer_token = controller_session.create_session(
            {"username": "aurora", "role": "customer"}
        )
        controller_header = controller_session.cookie_header(controller_token, area="controller")
        customer_header = controller_session.cookie_header(customer_token, area="customer")
        self.assertIn(f"{controller_session.CONTROLLER_SESSION_COOKIE}=", controller_header)
        self.assertNotIn(f"{controller_session.CUSTOMER_SESSION_COOKIE}=", controller_header)
        self.assertIn(f"{controller_session.CUSTOMER_SESSION_COOKIE}=", customer_header)
        self.assertNotIn(f"{controller_session.CONTROLLER_SESSION_COOKIE}=", customer_header)

    def test_wrong_area_cookie_is_not_accepted(self):
        customer_token = controller_session.create_session(
            {"username": "aurora", "role": "customer", "scope_id": 1}
        )
        headers = Headers(
            {"Cookie": f"{controller_session.CUSTOMER_SESSION_COOKIE}={customer_token}"}
        )
        self.assertIsNone(
            controller_session.session_user_from_headers(headers, area="controller")
        )
        customer = controller_session.session_user_from_headers(headers, area="customer")
        self.assertEqual(customer["role"], "customer")

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

    def test_browser_bridge_has_no_legacy_auth_state_or_basic_credential(self):
        bridge = (WEB / "browser-session-bridge.js").read_text(encoding="utf-8")
        for needle in (
            "COMPAT_VALUE",
            "cookie-session",
            "dsm_auth",
            "dsm_customer_auth",
            "sessionStorage",
            "Authorization",
            "btoa(",
        ):
            self.assertNotIn(needle, bridge)
        self.assertIn("X-Capivara-Auth-Area", bridge)
        self.assertIn("/api/auth/logout", bridge)
        self.assertIn("/api/customer/auth/logout", bridge)
        self.assertIn('credentials = "same-origin"', bridge)

    def test_login_frontends_do_not_persist_basic_credentials(self):
        admin = (WEB / "auth.js").read_text(encoding="utf-8")
        customer = (WEB / "customer-auth.js").read_text(encoding="utf-8")
        for source in (admin, customer):
            self.assertNotIn("sessionStorage", source)
            self.assertNotIn("localStorage", source)
        self.assertIn('/api/customer/auth/session', customer)
        self.assertIn('/api/auth/login', admin)
        self.assertIn('Authorization', admin)
        self.assertIn('Authorization', customer)

    def test_admin_dashboard_uses_controller_cookie_session_not_legacy_basic(self):
        source = (WEB / "dashboard-home-v3.js").read_text(encoding="utf-8")
        self.assertNotIn("sessionStorage", source)
        self.assertNotIn("Authorization", source)
        self.assertIn('credentials: "same-origin"', source)
        self.assertIn('"X-Capivara-Auth-Area": "controller"', source)
        self.assertIn('window.location.replace("/login.html")', source)

    def test_customer_dashboard_uses_customer_cookie_session_not_legacy_basic(self):
        source = (WEB / "customer.js").read_text(encoding="utf-8")
        self.assertNotIn("sessionStorage", source)
        self.assertNotIn("Authorization", source)
        self.assertIn('credentials: "same-origin"', source)
        self.assertIn('"X-Capivara-Auth-Area": "customer"', source)
        self.assertIn('user.role !== "customer"', source)
        self.assertIn('location.replace("/customer-login.html")', source)
        self.assertIn('"/api/customer/auth/logout"', source)

    def test_customer_dashboard_never_redirects_auth_failure_to_controller_login(self):
        source = (WEB / "customer.js").read_text(encoding="utf-8")
        self.assertNotIn('location.href = "/login.html"', source)
        self.assertNotIn('location.replace("/login.html")', source)
        self.assertIn("/customer-login.html", source)

    def test_final_composition_installs_browser_session_boundary(self):
        source = (DASHBOARD / "server_part17.py").read_text(encoding="utf-8")
        self.assertIn("install_browser_session_http", source)
        self.assertIn("browser_login_base.credential_authenticate", source)

    def test_transport_csp_allows_inline_styles_not_inline_scripts(self):
        source = (DASHBOARD / "tls_runtime.py").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", source)
        self.assertIn("style-src 'self' 'unsafe-inline'", source)
        self.assertIn("script-src 'self'", source)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", source)
        self.assertIn("frame-ancestors 'none'", source)
        self.assertIn("base-uri 'self'", source)
        self.assertIn("form-action 'self'", source)

    def test_browser_session_boundary_does_not_intercept_static_file_delivery(self):
        source = (DASHBOARD / "browser_session_http.py").read_text(encoding="utf-8")
        self.assertNotIn("_serve_html_with_bridge", source)
        self.assertNotIn("session_aware_send_file", source)
        self.assertNotIn("previous_send_file", source)
        self.assertNotIn("legacy.DashboardHandler.send_file =", source)


if __name__ == "__main__":
    unittest.main()
