#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))
sys.path.insert(0, str(ROOT / "dashboard"))

from system_user_admin_repository import SYSTEM_ROLES


class SystemUserTemporaryPasswordTest(unittest.TestCase):
    def test_system_roles_are_separate_from_customer(self):
        self.assertEqual({"admin", "controller", "operator"}, SYSTEM_ROLES)
        self.assertNotIn("customer", SYSTEM_ROLES)

    def test_repository_tracks_temporary_password_state(self):
        source = (ROOT / "database" / "system_user_admin_repository.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS system_password_state", source)
        self.assertIn("must_change_password", source)
        self.assertIn("secrets.token_urlsafe(12)", source)
        self.assertIn("change_temporary_password", source)
        self.assertIn("at least one active administrator is required", source)
        self.assertIn("the current administrator cannot remove its own access", source)

    def test_api_exposes_save_reset_and_change(self):
        source = (ROOT / "dashboard" / "system_user_admin_api.py").read_text(encoding="utf-8")
        self.assertIn('"/api/system-users/save"', source)
        self.assertIn('"/api/system-users/reset-password"', source)
        self.assertIn('"/api/system/auth/password-state"', source)
        self.assertIn('"/api/system/auth/change-password"', source)
        self.assertIn("system_user.password_reset", source)
        self.assertIn("system_user.temporary_password_changed", source)

    def test_http_composition_forces_rotation_before_system_pages(self):
        source = (ROOT / "dashboard" / "server_part13.py").read_text(encoding="utf-8")
        self.assertIn("SYSTEM_PASSWORD_GATED_PAGES", source)
        self.assertIn('"/system-change-password.html"', source)
        self.assertIn("SystemUserAdminRepository", source)
        self.assertIn("_require_system_password_rotation", source)
        self.assertIn("dispatch_system_user_post", source)

    def test_system_user_ui_handles_temporary_passwords(self):
        page = (ROOT / "dashboard" / "web" / "users.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "users.js").read_text(encoding="utf-8")
        change_page = (ROOT / "dashboard" / "web" / "system-change-password.html").read_text(encoding="utf-8")
        change_script = (ROOT / "dashboard" / "web" / "system-change-password.js").read_text(encoding="utf-8")
        self.assertIn("senha definida pelo administrador é provisória", page)
        self.assertIn('id="user-reset-password"', page)
        self.assertIn("/api/system-users/save", script)
        self.assertIn("/api/system-users/reset-password", script)
        self.assertIn("Troca obrigatória de senha", change_page)
        self.assertIn("/api/system/auth/change-password", change_script)

    def test_legacy_server_was_not_expanded_for_feature(self):
        server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("system_password_state", server)
        self.assertNotIn("/api/system-users/reset-password", server)


if __name__ == "__main__":
    unittest.main()
