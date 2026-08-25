#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from runtime_backend import backend_from_environment
from system_user_repository import SystemUserRepository
from users import hash_temporary_password, is_temporary_password_hash


class SystemUserFunctionalProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "capivara.db"
        self.backend = backend_from_environment({
            "DSM_DATABASE_DRIVER": "sqlite",
            "DSM_DATABASE": str(self.db),
        })
        self.backend.initialize()
        self.repo = SystemUserRepository(self.backend)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, username: str, email: str, *, role: str = "admin", active: bool = True):
        return self.repo.save(
            username=username,
            password_hash=hash_temporary_password("Temporary@123"),
            role=role,
            scope_id=None,
            active=active,
            full_name=f"User {username}",
            corporate_email=email,
            phone="+55 19 99999-0000",
            job_title="Operations Engineer",
            department="Infrastructure",
            created_by="bootstrap",
            require_functional_identity=True,
        )

    def test_functional_identity_is_persisted_with_temporary_password(self):
        user = self.create("admin.one", "ADMIN.ONE@example.com")
        self.assertEqual(user["full_name"], "User admin.one")
        self.assertEqual(user["corporate_email"], "admin.one@example.com")
        self.assertEqual(user["job_title"], "Operations Engineer")
        self.assertEqual(user["department"], "Infrastructure")
        self.assertTrue(is_temporary_password_hash(user["password_hash"]))

    def test_corporate_email_is_unique_case_insensitively(self):
        self.create("admin.one", "admin.one@example.com")
        with self.assertRaisesRegex(ValueError, "e-mail corporativo já cadastrado"):
            self.create("admin.two", "ADMIN.ONE@EXAMPLE.COM")
        self.assertIsNone(self.repo.get("admin.two"))

    def test_new_dashboard_account_requires_name_and_email(self):
        with self.assertRaisesRegex(ValueError, "nome completo é obrigatório"):
            self.repo.save(
                username="operator.one",
                password_hash=hash_temporary_password("Temporary@123"),
                role="operator",
                scope_id=None,
                active=True,
                corporate_email="operator.one@example.com",
                require_functional_identity=True,
            )
        with self.assertRaisesRegex(ValueError, "e-mail corporativo é obrigatório"):
            self.repo.save(
                username="operator.one",
                password_hash=hash_temporary_password("Temporary@123"),
                role="operator",
                scope_id=None,
                active=True,
                full_name="Operator One",
                require_functional_identity=True,
            )

    def test_last_admin_cannot_be_deleted_demoted_or_disabled(self):
        admin = self.create("admin.one", "admin.one@example.com")
        with self.assertRaisesRegex(ValueError, "último administrador do sistema"):
            self.repo.delete("admin.one")
        with self.assertRaisesRegex(ValueError, "último administrador"):
            self.repo.save(
                username="admin.one",
                password_hash=admin["password_hash"],
                role="operator",
                scope_id=None,
                active=True,
                full_name=admin["full_name"],
                corporate_email=admin["corporate_email"],
                phone=admin["phone"],
                job_title=admin["job_title"],
                department=admin["department"],
                created_by=admin["created_by"],
                require_functional_identity=True,
            )
        with self.assertRaisesRegex(ValueError, "último administrador ativo"):
            self.repo.save(
                username="admin.one",
                password_hash=admin["password_hash"],
                role="admin",
                scope_id=None,
                active=False,
                full_name=admin["full_name"],
                corporate_email=admin["corporate_email"],
                phone=admin["phone"],
                job_title=admin["job_title"],
                department=admin["department"],
                created_by=admin["created_by"],
                require_functional_identity=True,
            )
        self.create("admin.two", "admin.two@example.com")
        self.repo.delete("admin.one")
        self.assertIsNone(self.repo.get("admin.one"))
        self.assertIsNotNone(self.repo.get("admin.two"))

    def test_compiled_baseline_contains_functional_columns(self):
        with self.backend.connect() as connection:
            rows = connection.execute("PRAGMA table_info(dashboard_users)").fetchall()
        columns = {str(row[1]) for row in rows}
        for name in (
            "full_name",
            "corporate_email",
            "phone",
            "job_title",
            "department",
            "created_by",
        ):
            self.assertIn(name, columns)


if __name__ == "__main__":
    unittest.main()
