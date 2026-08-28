#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

from customer_session_auth import authenticate_browser_customer


class CustomerSessionAuthTest(unittest.TestCase):
    def test_session_cookie_identity_has_priority(self):
        calls = []

        def session_auth(headers):
            calls.append("session")
            return {
                "username": "customer@example.test",
                "role": "customer",
                "scope_id": "customer-1",
            }

        def fallback_auth(headers):
            calls.append("fallback")
            return None

        user = authenticate_browser_customer(
            {"Cookie": "capivara_customer_session=abc"},
            session_authenticator=session_auth,
            fallback_authenticator=fallback_auth,
        )

        self.assertEqual("customer", user["role"])
        self.assertEqual(["session"], calls)

    def test_header_auth_remains_fallback(self):
        calls = []

        def session_auth(headers):
            calls.append("session")
            return None

        def fallback_auth(headers):
            calls.append("fallback")
            return {
                "username": "legacy-customer",
                "role": "customer",
                "scope_id": "customer-2",
            }

        user = authenticate_browser_customer(
            {"Authorization": "Basic example"},
            session_authenticator=session_auth,
            fallback_authenticator=fallback_auth,
        )

        self.assertEqual("customer-2", user["scope_id"])
        self.assertEqual(["session", "fallback"], calls)

    def test_missing_authentication_returns_none(self):
        user = authenticate_browser_customer(
            {},
            session_authenticator=lambda headers: None,
            fallback_authenticator=lambda headers: None,
        )
        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
