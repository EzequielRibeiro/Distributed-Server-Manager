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
            "Cookie": "capivara_controller_session=still-valid",
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
            [("controller", "Basic invalid")],
            calls,
        )

    def test_current_credentials_select_identity(self):
        expected = {"username": "operator", "role": "operator"}
        self.assertEqual(
            expected,
            authenticate_login_credentials(
                {"Authorization": "Basic valid", "Cookie": "capivara_controller_session=admin"},
                controller_authenticator=lambda headers: expected,
                customer_authenticator=lambda headers: None,
            ),
        )

    def test_admin_login_does_not_call_customer_authenticator(self):
        calls = []

        def broken_customer(headers):
            calls.append("customer")
            raise RuntimeError("customer authenticator must not be called")

        self.assertIsNone(
            authenticate_login_credentials(
                {"Authorization": "Basic value"},
                controller_authenticator=lambda headers: None,
                customer_authenticator=broken_customer,
            )
        )
        self.assertEqual([], calls)

    def test_final_browser_login_boundary_is_area_isolated(self):
        source = (
            ROOT / "dashboard" / "browser_session_http.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'if path == ADMIN_LOGIN_PATH:',
            source,
        )
        self.assertIn(
            'if path == CUSTOMER_LOGIN_PATH:',
            source,
        )

        self.assertIn(
            'session_token_from_headers(self.headers, area="controller")',
            source,
        )
        self.assertIn(
            'session_token_from_headers(self.headers, area="customer")',
            source,
        )

        self.assertIn(
            'cookie_header(token, area="controller")',
            source,
        )
        self.assertIn(
            'cookie_header(token, area="customer")',
            source,
        )

        self.assertIn(
            'expired_cookie_header(area="controller")',
            source,
        )
        self.assertIn(
            'expired_cookie_header(area="customer")',
            source,
        )

        self.assertIn(
            'user.get("role") not in {"admin", "controller", "operator"}',
            source,
        )
        self.assertIn(
            'user.get("role") != "customer"',
            source,
        )



if __name__ == "__main__":
    unittest.main()
