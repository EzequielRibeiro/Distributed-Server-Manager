#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(0, str(DATABASE_DIR))

from alert_repository import (
    AlertRepository,
    dialect_for_backend,
)
from backend import (
    DatabaseConfig,
    DatabaseConfigurationError,
)
from backend_factory import create_backend


class NamedBackend:
    def __init__(self, name):
        self.name = name


class AlertRepositoryDialectTest(unittest.TestCase):

    def test_driver_placeholders(self):
        self.assertEqual(
            dialect_for_backend(NamedBackend("sqlite")).placeholder,
            "?",
        )
        self.assertEqual(
            dialect_for_backend(NamedBackend("postgresql")).placeholder,
            "%s",
        )
        self.assertEqual(
            dialect_for_backend(NamedBackend("mysql")).placeholder,
            "%s",
        )

    def test_pagination_without_limit_is_portable(self):
        expected = {
            "sqlite": " LIMIT -1 OFFSET ?",
            "postgresql": " OFFSET %s",
            "mysql": (
                " LIMIT 18446744073709551615 OFFSET %s"
            ),
        }

        for name, sql in expected.items():
            with self.subTest(name=name):
                dialect = dialect_for_backend(
                    NamedBackend(name)
                )
                self.assertEqual(
                    dialect.pagination(
                        limit=None,
                        offset=7,
                    ),
                    (sql, [7]),
                )

    def test_limited_pagination_parameter_order(self):
        dialect = dialect_for_backend(
            NamedBackend("postgresql")
        )
        self.assertEqual(
            dialect.pagination(limit=20, offset=5),
            (" LIMIT %s OFFSET %s", [20, 5]),
        )

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(
            DatabaseConfigurationError
        ):
            dialect_for_backend(
                NamedBackend("oracle")
            )


class AlertRepositorySQLiteTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Path(self.temp.name) / "capivara.db"
        backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(database),
            )
        )
        self.repository = AlertRepository(backend)
        self.repository.initialize()

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def test_get_missing_alert(self):
        self.assertIsNone(
            self.repository.get_alert("missing")
        )

    def test_history_for_missing_alert(self):
        self.assertEqual(
            self.repository.alert_history("missing"),
            [],
        )

    def test_transaction_session_commits(self):
        with self.repository.transaction() as session:
            session.execute(
                """
                INSERT INTO nodes(id, name, role, status)
                VALUES (?,?,?,?)
                """,
                (
                    "controller-node",
                    "Controller node",
                    "controller",
                    "active",
                ),
            )
            session.execute(
                """
                INSERT INTO controllers(id, node_id, name, status)
                VALUES (?,?,?,?)
                """,
                (
                    "controller1",
                    "controller-node",
                    "Controller",
                    "active",
                ),
            )
            session.execute(
                """
                INSERT INTO alerts(
                    id, scope, controller_id, rule_id,
                    level, state, message
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    "repository-alert",
                    "controller",
                    "controller1",
                    "repository-rule",
                    "WARNING",
                    "OPEN",
                    "Repository test",
                ),
            )

        alert = self.repository.get_alert(
            "repository-alert"
        )
        self.assertEqual(alert["state"], "OPEN")

    def test_suppression_minutes_are_validated(self):
        with self.assertRaises(ValueError):
            self.repository.suppression_deadline(0)


if __name__ == "__main__":
    unittest.main()
