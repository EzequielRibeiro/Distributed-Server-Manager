#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class CustomerAuthDomainFrontendTest(unittest.TestCase):
    CUSTOMER_MODULES = (
        "customer.js",
        "customer-account.js",
        "customer-backups.js",
        "customer-integrations.js",
        "customer-members.js",
        "customer-navigation.js",
    )

    def read(self, name: str) -> str:
        return (WEB / name).read_text(encoding="utf-8")

    def test_customer_modules_do_not_use_controller_legacy_auth_state(self):
        for name in self.CUSTOMER_MODULES:
            with self.subTest(name=name):
                source = self.read(name)
                self.assertNotIn('sessionStorage.getItem("dsm_auth")', source)
                self.assertNotIn('sessionStorage.setItem("dsm_auth"', source)
                self.assertNotIn("Authorization: `Basic", source)
                self.assertNotIn('location.href = "/login.html"', source)
                self.assertNotIn('location.replace("/login.html")', source)

    def test_customer_modules_use_cookie_session_transport(self):
        for name in self.CUSTOMER_MODULES:
            with self.subTest(name=name):
                source = self.read(name)
                self.assertRegex(
                    source,
                    re.compile(r'credentials\s*:\s*"same-origin"'),
                )
                self.assertIn("/customer-login.html", source)

    def test_customer_pages_validate_dedicated_customer_session(self):
        for name in (
            "customer-account.js",
            "customer-backups.js",
            "customer-integrations.js",
            "customer-members.js",
        ):
            with self.subTest(name=name):
                self.assertIn(
                    "/api/customer/auth/session",
                    self.read(name),
                )

    def test_customer_shell_never_loads_controller_bridge(self):
        source = self.read("customer-shell.js")
        self.assertNotIn("browser-session-bridge.js", source)
        self.assertIn("/api/customer/auth/session", source)
        self.assertIn('session.role !== "customer"', source)
        self.assertIn("/customer-navigation.js?v=2", source)
        self.assertIn("/customer-core.js?v=3", source)

    def test_customer_asset_versions_force_new_browser_code(self):
        self.assertIn('/customer.js?v=4', self.read("customer.html"))
        self.assertIn('/customer-account.js?v=2', self.read("customer-account.html"))
        self.assertIn('/customer-backups.js?v=2', self.read("customer-backups.html"))
        self.assertIn('/customer-integrations.js?v=2', self.read("customer-integrations.html"))
        self.assertIn('/customer-members.js?v=2', self.read("customer-members.html"))


if __name__ == "__main__":
    unittest.main()
