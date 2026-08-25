#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from system_user_admin_http import _active_admin_count, _admin_count, _safe_user
from users import hash_temporary_password, is_temporary_password_hash, verify_password


class SystemUserSecurityTest(unittest.TestCase):
    def test_temporary_hash_verifies_without_storing_plaintext(self):
        encoded = hash_temporary_password("Temporary-123!")
        self.assertTrue(is_temporary_password_hash(encoded))
        self.assertNotIn("Temporary-123!", encoded)
        self.assertTrue(verify_password("Temporary-123!", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_single_admin_is_marked_not_deletable(self):
        users = {
            "root": {"username": "root", "role": "admin", "active": True, "password_hash": "x"},
            "ops": {"username": "ops", "role": "operator", "active": True, "password_hash": "x"},
        }
        item = _safe_user(users["root"], admin_count=_admin_count(users), active_admin_count=_active_admin_count(users))
        self.assertFalse(item["delete_allowed"])

    def test_only_active_admin_is_marked_not_deletable(self):
        users = {
            "root": {"username": "root", "role": "admin", "active": True, "password_hash": "x"},
            "backup": {"username": "backup", "role": "admin", "active": False, "password_hash": "x"},
        }
        item = _safe_user(users["root"], admin_count=_admin_count(users), active_admin_count=_active_admin_count(users))
        self.assertFalse(item["delete_allowed"])
        backup = _safe_user(users["backup"], admin_count=_admin_count(users), active_admin_count=_active_admin_count(users))
        self.assertTrue(backup["delete_allowed"])

    def test_two_active_admins_are_individually_deletable(self):
        users = {
            "one": {"username": "one", "role": "admin", "active": True, "password_hash": "x"},
            "two": {"username": "two", "role": "admin", "active": True, "password_hash": "x"},
        }
        self.assertEqual(_admin_count(users), 2)
        self.assertEqual(_active_admin_count(users), 2)
        for item in users.values():
            public = _safe_user(item, admin_count=2, active_admin_count=2)
            self.assertTrue(public["delete_allowed"])


if __name__ == "__main__":
    unittest.main()
