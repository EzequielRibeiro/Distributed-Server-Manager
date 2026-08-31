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
        self.assertEqual(dialect_for_backend(NamedBackend("sqlite")).placeholder, "?")
        self.assertEqual(dialect_for_backend(NamedBackend("postgresql")).placeholder, "%s")
        self.assertEqual(dialect_for_backend(NamedBackend("mysql")).placeholder, "%s")

    def test_pagination_without_limit_is_portable(self):
        expected = {
            "sqlite": " LIMIT -1 OFFSET ?",
            "postgresql": " OFFSET %s",
            "mysql": " LIMIT 18446744073709551615 OFFSET %s",
        }
        for name, sql in expected.items():
            with self.subTest(name=name):
                dialect = dialect_for_backend(NamedBackend(name))
                self.assertEqual(dialect.pagination(limit=None, offset=7), (sql, [7]))

    def test_limited_pagination_parameter_order(self):
        dialect = dialect_for_backend(NamedBackend("postgresql"))
        self.assertEqual(dialect.pagination(limit=20, offset=5), (" LIMIT %s OFFSET %s", [20, 5]))

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(DatabaseConfigurationError):
            dialect_for_backend(NamedBackend("oracle"))


class AlertRepositorySQLiteTest(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Path(self.temp.name) / "capivara.db"
        backend = create_backend(DatabaseConfig(driver="sqlite", database=str(database)))
        self.repository = AlertRepository(backend)
        self.repository.initialize()

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def _seed_controller(self):
        with self.repository.transaction() as session:
            session.execute("INSERT INTO nodes(id, name, role, status) VALUES (?,?,?,?)", ("controller-node", "Controller node", "controller", "active"))
            session.execute("INSERT INTO controllers(id, node_id, name, status) VALUES (?,?,?,?)", ("controller1", "controller-node", "Controller", "active"))

    def _open(self, alert_id="lifecycle", level="WARNING", message="Lifecycle"):
        return self.repository.open_alert(
            alert_id=alert_id,
            rule_id="rule.lifecycle",
            level=level,
            message=message,
            scope="controller",
            controller_id="controller1",
        )

    def test_get_missing_alert(self):
        self.assertIsNone(self.repository.get_alert("missing"))

    def test_history_for_missing_alert(self):
        self.assertEqual(self.repository.alert_history("missing"), [])

    def test_transaction_session_commits(self):
        self._seed_controller()
        with self.repository.transaction() as session:
            session.execute(
                "INSERT INTO alerts(id, scope, controller_id, rule_id, level, state, message) VALUES (?,?,?,?,?,?,?)",
                ("repository-alert", "controller", "controller1", "repository-rule", "WARNING", "OPEN", "Repository test"),
            )
        self.assertEqual(self.repository.get_alert("repository-alert")["state"], "OPEN")

    def test_alert_lifecycle(self):
        self._seed_controller()
        opened = self._open()
        self.assertEqual(opened["action"], "OPEN")
        acknowledged = self.repository.acknowledge_alert("lifecycle")
        self.assertEqual(acknowledged["state"], "ACKNOWLEDGED")
        resolved = self.repository.resolve_alert("lifecycle")
        self.assertEqual(resolved["state"], "RESOLVED")
        reopened = self.repository.open_alert(
            alert_id="lifecycle",
            rule_id="rule.lifecycle",
            level="CRITICAL",
            message="Reopened",
            scope="controller",
            controller_id="controller1",
        )
        self.assertEqual(reopened["action"], "REOPEN")
        self.assertEqual(len(self.repository.alert_history("lifecycle")), 4)

    def test_note_does_not_change_state(self):
        self._seed_controller()
        self._open()
        updated = self.repository.note_alert("lifecycle", "Host clonado removido.")
        self.assertEqual(updated["state"], "OPEN")
        history = self.repository.alert_history("lifecycle")
        self.assertEqual(history[-1]["action"], "NOTE")
        self.assertEqual(history[-1]["message"], "Host clonado removido.")

    def test_resolve_with_note_and_manual_reopen(self):
        self._seed_controller()
        self._open()
        resolved = self.repository.resolve_alert("lifecycle", note="Agent reinstalado e revinculado.")
        self.assertEqual(resolved["state"], "RESOLVED")
        self.assertEqual(self.repository.alert_history("lifecycle")[-1]["message"], "Agent reinstalado e revinculado.")
        reopened = self.repository.reopen_alert("lifecycle", note="Conflito voltou a ocorrer.")
        self.assertEqual(reopened["state"], "OPEN")
        history = self.repository.alert_history("lifecycle")
        self.assertEqual(history[-1]["action"], "REOPEN")
        self.assertEqual(history[-1]["message"], "Conflito voltou a ocorrer.")

    def test_manual_reopen_rejects_active_alert(self):
        self._seed_controller()
        self._open()
        with self.assertRaises(ValueError):
            self.repository.reopen_alert("lifecycle", note="Ainda ativo")

    def test_list_count_and_suppress(self):
        self._seed_controller()
        self._open(alert_id="query-alert", level="CRITICAL", message="Query")
        self.assertEqual(self.repository.count_alerts(active_only=True), 1)
        self.assertEqual(self.repository.list_alerts(active_only=True, limit=1)[0]["id"], "query-alert")
        suppressed = self.repository.suppress_alert("query-alert", 5)
        self.assertEqual(suppressed["state"], "SUPPRESSED")
        self.assertEqual(self.repository.count_alerts(active_only=True), 0)

    def test_suppression_minutes_are_validated(self):
        with self.assertRaises(ValueError):
            self.repository.suppression_deadline(0)


if __name__ == "__main__":
    unittest.main()
