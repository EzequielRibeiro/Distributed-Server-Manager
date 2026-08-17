#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from user_repository import UserRepository


class UserRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.repository = UserRepository(backend)

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def test_create_replace_and_password(self):
        user = self.repository.save(
            username="admin.test", password_hash="hash-1", role="admin"
        )
        self.assertEqual(user["role"], "admin")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.repository.save(
                username="admin.test", password_hash="hash-2", role="admin"
            )
        self.repository.save(
            username="admin.test", password_hash="hash-2",
            role="operator", replace=True,
        )
        self.repository.change_password("admin.test", "hash-3")
        self.assertEqual(self.repository.get("admin.test")["password_hash"], "hash-3")

    def test_scope_must_exist(self):
        with self.assertRaisesRegex(ValueError, "scope does not exist"):
            self.repository.save(
                username="customer.test", password_hash="hash",
                role="customer", scope_id="missing",
            )

    def test_list_and_delete(self):
        self.repository.save(
            username="admin.one", password_hash="hash", role="admin"
        )
        self.repository.save(
            username="admin.two", password_hash="hash", role="admin"
        )
        self.assertEqual(len(self.repository.list_users()), 2)
        self.repository.delete("admin.two")
        with self.assertRaisesRegex(ValueError, "last active"):
            self.repository.delete("admin.one")

    def test_missing_password_user(self):
        with self.assertRaisesRegex(ValueError, "não encontrado"):
            self.repository.change_password("missing", "hash")


if __name__ == "__main__":
    unittest.main()
