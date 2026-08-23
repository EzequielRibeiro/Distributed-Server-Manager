#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

from login_credentials import authenticate_login_credentials


class LoginCredentialIsolationTest(unittest.TestCase):
    def test_invalid_credentials_cannot_inherit_existing_session(self):
        headers = {
            "Authorization": "Basic invalid",
            "Cookie": "capivara_session=still-valid",
        }
        calls = []

        def controller(request_headers):
            calls.append(("controller", request_headers["Authorization"]))
            return None

        def customer(request_headers):
            calls.append(("customer", request_headers["Authorization"]))
            return None

        self.assertIsNone(
            authenticate_login_credentials(
                headers,
                controller_authenticator=controller,
                customer_authenticator=customer,
            )
        )
        self.assertEqual(
            [("controller", "Basic invalid"), ("customer", "Basic invalid")],
            calls,
        )

    def test_current_credentials_select_identity(self):
        expected = {"username": "operator", "role": "operator"}
        self.assertEqual(
            expected,
            authenticate_login_credentials(
                {"Authorization": "Basic valid", "Cookie": "capivara_session=admin"},
                controller_authenticator=lambda headers: expected,
                customer_authenticator=lambda headers: None,
            ),
        )

    def test_customer_backend_failure_fails_closed(self):
        def broken_customer(headers):
            raise RuntimeError("database unavailable")

        self.assertIsNone(
            authenticate_login_credentials(
                {"Authorization": "Basic value"},
                controller_authenticator=lambda headers: None,
                customer_authenticator=broken_customer,
            )
        )

    def test_http_login_uses_isolated_credentials_and_expires_old_cookie(self):
        source = (ROOT / "dashboard" / "server_part8.py").read_text(encoding="utf-8")
        login_block = source.split('if path=="/api/auth/login":', 1)[1].split(
            'if path=="/api/instance/delete":', 1
        )[0]
        self.assertIn("credential_authenticate(self.headers)", login_block)
        self.assertNotIn("integrated_authenticate(self.headers)", login_block)
        self.assertIn("reject_login(self)", login_block)
        self.assertIn("expired_cookie_header()", source)
        self.assertIn("revoke_session(token)", source)


if __name__ == "__main__":
    unittest.main()
