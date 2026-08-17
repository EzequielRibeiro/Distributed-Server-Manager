#!/usr/bin/env python3
"""Real database integration tests for UserRepository."""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from runtime_backend import backend_from_environment
from user_repository import UserRepository


ENABLED = (
    os.environ.get("DSM_USER_REPOSITORY_INTEGRATION", "").strip()
    == "1"
)


@unittest.skipUnless(
    ENABLED,
    "set DSM_USER_REPOSITORY_INTEGRATION=1",
)
class UserRepositoryIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repository = UserRepository(
            backend_from_environment()
        )
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.first = f"integration.{suffix}.one"
        self.second = f"integration.{suffix}.two"

    def tearDown(self):
        placeholder = self.repository.dialect.placeholder
        with self.repository.session(transaction=True) as session:
            session.execute(
                "DELETE FROM dashboard_users WHERE username IN "
                f"({self.repository.dialect.parameters(2)})",
                (self.first, self.second),
            )

    def test_create_replace_password_list_and_delete(self):
        created = self.repository.save(
            username=self.first,
            password_hash="integration-hash-1",
            role="operator",
        )
        self.assertEqual(created["username"], self.first)
        self.assertEqual(created["role"], "operator")

        with self.assertRaisesRegex(ValueError, "already exists"):
            self.repository.save(
                username=self.first,
                password_hash="duplicate",
                role="operator",
            )

        replaced = self.repository.save(
            username=self.first,
            password_hash="integration-hash-2",
            role="operator",
            replace=True,
        )
        self.assertEqual(replaced["role"], "operator")

        self.repository.change_password(
            self.first,
            "integration-hash-3",
        )
        self.assertEqual(
            self.repository.get(self.first)["password_hash"],
            "integration-hash-3",
        )

        usernames = {
            row["username"]
            for row in self.repository.list_users()
        }
        self.assertIn(self.first, usernames)

        self.repository.delete(self.first)
        self.assertIsNone(self.repository.get(self.first))

    def test_last_test_administrator_is_protected(self):
        self.repository.save(
            username=self.first,
            password_hash="integration-hash",
            role="admin",
        )
        self.repository.save(
            username=self.second,
            password_hash="integration-hash",
            role="admin",
        )

        self.repository.delete(self.second)

        # Production databases may already contain another active admin.
        # Verify protection only when this is the remaining active one.
        placeholder = self.repository.dialect.placeholder
        with self.repository.session() as session:
            row = session.execute(
                "SELECT COUNT(*) AS total FROM dashboard_users "
                "WHERE role='admin' AND active=1 AND username<>"
                + placeholder,
                (self.first,),
            ).fetchone()

        if int(row["total"]) == 0:
            with self.assertRaisesRegex(ValueError, "last active"):
                self.repository.delete(self.first)
        else:
            self.repository.delete(self.first)


if __name__ == "__main__":
    unittest.main()
