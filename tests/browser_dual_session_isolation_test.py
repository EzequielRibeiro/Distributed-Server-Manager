#!/usr/bin/env python3
"""Regression tests for simultaneous Controller and Customer browser sessions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"

if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))

import controller_session


class Headers:
    def __init__(self, cookie: str = ""):
        self._cookie = cookie

    def get(self, name: str, default=None):
        if name.lower() == "cookie":
            return self._cookie
        return default


class BrowserDualSessionIsolationTest(unittest.TestCase):

    def setUp(self):
        # Never use the production/session runtime store during unit tests.
        self.tempdir = tempfile.TemporaryDirectory()
        controller_session.SESSION_FILE = (
            Path(self.tempdir.name) / "sessions.json"
        )

        # controller_session keeps process-global in-memory state, therefore
        # both the registry and load marker must be reset for every test.
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded = False

        self.admin = {
            "username": "admin-test",
            "role": "admin",
            "scope_id": "controller-test",
        }

        self.customer = {
            "username": "aurora-test",
            "role": "customer",
            "scope_id": "cli-test",
            "customer_id": "cli-test",
            "customer_code": "CLI-TEST",
        }

    def tearDown(self):
        with controller_session._lock:
            controller_session._sessions.clear()
            controller_session._loaded = False

        self.tempdir.cleanup()

    def sessions(self):
        controller_token = controller_session.create_session(
            self.admin,
            area="controller",
        )
        customer_token = controller_session.create_session(
            self.customer,
            area="customer",
        )
        return controller_token, customer_token

    def combined_headers(self, controller_token, customer_token):
        return Headers(
            f"{controller_session.CONTROLLER_SESSION_COOKIE}={controller_token}; "
            f"{controller_session.CUSTOMER_SESSION_COOKIE}={customer_token}"
        )

    def test_controller_and_customer_sessions_coexist(self):
        controller_token, customer_token = self.sessions()
        headers = self.combined_headers(controller_token, customer_token)

        controller = controller_session.session_user_from_headers(
            headers,
            area="controller",
        )
        customer = controller_session.session_user_from_headers(
            headers,
            area="customer",
        )

        self.assertIsNotNone(controller)
        self.assertEqual("admin", controller["role"])
        self.assertEqual("admin-test", controller["username"])

        self.assertIsNotNone(customer)
        self.assertEqual("customer", customer["role"])
        self.assertEqual("aurora-test", customer["username"])
        self.assertEqual("CLI-TEST", customer["customer_code"])

    def test_moving_controller_token_into_customer_cookie_fails_closed(self):
        controller_token, _ = self.sessions()

        headers = Headers(
            f"{controller_session.CUSTOMER_SESSION_COOKIE}={controller_token}"
        )

        self.assertIsNone(
            controller_session.session_user_from_headers(
                headers,
                area="customer",
            )
        )

    def test_moving_customer_token_into_controller_cookie_fails_closed(self):
        _, customer_token = self.sessions()

        headers = Headers(
            f"{controller_session.CONTROLLER_SESSION_COOKIE}={customer_token}"
        )

        self.assertIsNone(
            controller_session.session_user_from_headers(
                headers,
                area="controller",
            )
        )

    def test_customer_logout_does_not_destroy_controller_session(self):
        controller_token, customer_token = self.sessions()

        controller_session.revoke_session(customer_token)

        headers = self.combined_headers(controller_token, customer_token)

        controller = controller_session.session_user_from_headers(
            headers,
            area="controller",
        )
        customer = controller_session.session_user_from_headers(
            headers,
            area="customer",
        )

        self.assertIsNotNone(controller)
        self.assertEqual("admin", controller["role"])
        self.assertIsNone(customer)

    def test_controller_logout_does_not_destroy_customer_session(self):
        controller_token, customer_token = self.sessions()

        controller_session.revoke_session(controller_token)

        headers = self.combined_headers(controller_token, customer_token)

        controller = controller_session.session_user_from_headers(
            headers,
            area="controller",
        )
        customer = controller_session.session_user_from_headers(
            headers,
            area="customer",
        )

        self.assertIsNone(controller)
        self.assertIsNotNone(customer)
        self.assertEqual("customer", customer["role"])

    def test_cookie_headers_use_independent_names(self):
        controller_token, customer_token = self.sessions()

        controller_cookie = controller_session.cookie_header(
            controller_token,
            area="controller",
        )
        customer_cookie = controller_session.cookie_header(
            customer_token,
            area="customer",
        )

        self.assertIn(
            f"{controller_session.CONTROLLER_SESSION_COOKIE}=",
            controller_cookie,
        )
        self.assertNotIn(
            f"{controller_session.CUSTOMER_SESSION_COOKIE}=",
            controller_cookie,
        )

        self.assertIn(
            f"{controller_session.CUSTOMER_SESSION_COOKIE}=",
            customer_cookie,
        )
        self.assertNotIn(
            f"{controller_session.CONTROLLER_SESSION_COOKIE}=",
            customer_cookie,
        )


if __name__ == "__main__":
    unittest.main()
