#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from baseline_upgrade_engine import _upgrade_alert_customer_identity
from customer_health_repository import CustomerHealthRepository


class SQLiteBackend:
    name = "sqlite"


class CustomerHealthAlertIdentityTest(unittest.TestCase):
    def test_upgrade_adds_customer_identity_idempotently(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            connection.execute(
                "CREATE TABLE alerts(id TEXT PRIMARY KEY, scope TEXT NOT NULL)"
            )
            _upgrade_alert_customer_identity(SQLiteBackend(), connection)
            _upgrade_alert_customer_identity(SQLiteBackend(), connection)
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(alerts)").fetchall()
            }
            self.assertIn("customer_id", columns)
        finally:
            connection.close()

    def test_customer_incident_uses_valid_controller_scope(self):
        repository = CustomerHealthRepository(SQLiteBackend())
        repository.alerts = MagicMock()
        repository.alerts.get_alert.return_value = None
        repository.alerts.open_alert.return_value = {
            "id": "customer-health-1",
            "state": "OPEN",
            "level": "WARNING",
            "action": "OPEN",
        }

        result = repository.open_or_recur(
            dedupe_key="placement:1",
            customer_id="42",
            controller_id="controller-a",
            event_type="CUSTOMER_INSTANCE_PLACEMENT_BLOCKED",
            severity="WARNING",
            message="Provisionamento bloqueado.",
        )

        kwargs = repository.alerts.open_alert.call_args.kwargs
        self.assertEqual(kwargs["scope"], "controller")
        self.assertEqual(kwargs["controller_id"], "controller-a")
        self.assertEqual(kwargs["customer_id"], "42")
        self.assertEqual(result["customer_id"], "42")
        self.assertEqual(result["transition"], "OPEN")


if __name__ == "__main__":
    unittest.main()
