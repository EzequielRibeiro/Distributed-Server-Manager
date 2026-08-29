#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"
LOGIN_EXEMPT = {"auth.js", "customer-auth.js"}
CUSTOMER_FILES = {
    "create-server-wizard.js", "customer-backup-transfer.js",
    "customer-change-password.js", "customer-deleted-backups.js",
    "customer-deletion-v2.js", "customer-email-change.js",
    "customer-instance-activity.js", "customer-instance-connection.js",
    "customer-instance-delete.js", "customer-instance-events.js",
    "customer-instance-v2.js", "customer-instance.js", "customer-members.js",
    "customer-navigation.js", "customer-placement-selector.js",
    "customer-profile.js", "customer-shell.js", "customer.js",
    "customer-backups.js", "customer-integrations.js", "customer-account.js",
    "runtime-selector.js",
}


class BrowserAuthLegacyDependencyTest(unittest.TestCase):
    def javascript(self):
        return sorted(WEB.rglob("*.js"))

    def test_no_browser_auth_state_in_web_storage(self):
        failures = []
        for path in self.javascript():
            text = path.read_text(encoding="utf-8")
            for needle in ("dsm_auth", "dsm_customer_auth", "sessionStorage.clear()"):
                if needle in text:
                    failures.append(f"{path.relative_to(ROOT)}: {needle}")
        self.assertEqual([], failures, "legacy browser auth state remains:\n" + "\n".join(failures))

    def test_basic_authorization_exists_only_for_initial_login_exchange(self):
        failures = []
        for path in self.javascript():
            text = path.read_text(encoding="utf-8")
            if path.name in LOGIN_EXEMPT:
                continue
            if re.search(r'Authorization\s*:\s*(?:`|["\'])Basic', text):
                failures.append(str(path.relative_to(ROOT)))
        self.assertEqual([], failures, "legacy Basic auth remains in authenticated modules:\n" + "\n".join(failures))

        admin = (WEB / "auth.js").read_text(encoding="utf-8")
        customer = (WEB / "customer-auth.js").read_text(encoding="utf-8")
        self.assertIn('/api/auth/login', admin)
        self.assertIn('Authorization', admin)
        self.assertIn('/api/customer/auth/session', customer)
        self.assertIn('Authorization', customer)

    def test_customer_modules_never_redirect_to_controller_login(self):
        failures = []
        for name in sorted(CUSTOMER_FILES):
            path = WEB / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r'location\.(?:href|replace)[^\n;]*?/login\.html', text):
                failures.append(name)
        self.assertEqual([], failures, "Customer modules redirect to Controller login:\n" + "\n".join(failures))

    def test_active_portals_explicitly_select_auth_area(self):
        required = {
            "dashboard-home-v3.js": "controller",
            "agents-v3.js": "controller",
            "agents.js": "controller",
            "users.js": "controller",
            "operations.js": "controller",
            "observability.js": "controller",
            "system.js": "controller",
            "infrastructure-v3.js": "controller",
            "customer.js": "customer",
            "customer-instance-v2.js": "customer",
            "runtime-selector.js": "customer",
        }
        failures = []
        for name, area in required.items():
            text = (WEB / name).read_text(encoding="utf-8")
            if "X-Capivara-Auth-Area" not in text or area not in text:
                failures.append(f"{name}: {area}")
        self.assertEqual([], failures, "active portal missing explicit auth area:\n" + "\n".join(failures))

    def test_customer_core_accepts_only_customer_identity(self):
        text = (WEB / "customer.js").read_text(encoding="utf-8")
        self.assertIn('user.role !== "customer"', text)
        self.assertNotIn('"admin",\n        "controller"', text)

    def test_password_change_never_rebuilds_browser_credentials(self):
        text = (WEB / "system-change-password.js").read_text(encoding="utf-8")
        self.assertNotIn("sessionStorage", text)
        self.assertNotIn("Authorization", text)
        self.assertIn('/api/auth/logout', text)

    def test_session_bridge_has_no_legacy_credential_compatibility(self):
        text = (WEB / "browser-session-bridge.js").read_text(encoding="utf-8")
        for needle in ("sessionStorage", "dsm_auth", "dsm_customer_auth", "COMPAT_VALUE"):
            self.assertNotIn(needle, text)
        self.assertIn("X-Capivara-Auth-Area", text)


if __name__ == "__main__":
    unittest.main()
