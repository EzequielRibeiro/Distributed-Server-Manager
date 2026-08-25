#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SystemUserDashboardContractTest(unittest.TestCase):
    def test_registration_collects_functional_identity_without_password_field(self):
        html = (ROOT / "dashboard/web/users.html").read_text(encoding="utf-8")
        for identifier in (
            'id="user-full-name"',
            'id="user-email"',
            'id="user-phone"',
            'id="user-job-title"',
            'id="user-department"',
        ):
            self.assertIn(identifier, html)
        self.assertNotIn('id="user-password"', html)
        self.assertIn("senha temporária", html.lower())

    def test_ui_disables_protected_admin_deletion(self):
        script = (ROOT / "dashboard/web/users.js").read_text(encoding="utf-8")
        self.assertIn("user.delete_allowed === false", script)
        self.assertIn("remove.disabled = protectedAdmin", script)
        self.assertIn("corporate_email", script)
        self.assertIn("full_name", script)

    def test_http_layer_requires_admin_and_functional_identity(self):
        source = (ROOT / "dashboard/system_user_admin_http.py").read_text(encoding="utf-8")
        self.assertIn("_require_admin", source)
        self.assertIn("require_functional_identity=True", source)
        self.assertIn("Acesso exclusivo de administradores", source)
        self.assertIn("temporary_password", source)
        self.assertIn("CHANGE_PASSWORD_PAGE", source)


if __name__ == "__main__":
    unittest.main()
