#!/usr/bin/env python3
"""Real database integration tests for AlertRepository.

Enable with DSM_ALERT_REPOSITORY_INTEGRATION=1 and configure the
target using the standard DSM_DATABASE_* environment variables.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(0, str(DATABASE_DIR))

from alert_repository import AlertRepository
from runtime_backend import backend_from_environment


ENABLED = (
    os.environ.get(
        "DSM_ALERT_REPOSITORY_INTEGRATION",
        "",
    ).strip()
    == "1"
)


@unittest.skipUnless(
    ENABLED,
    "set DSM_ALERT_REPOSITORY_INTEGRATION=1",
)
class AlertRepositoryIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repository = AlertRepository(
            backend_from_environment()
        )
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls):
        cls.repository.close()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.node_id = f"alert-test-node-{suffix}"
        self.controller_id = f"alert-test-controller-{suffix}"
        self.alert_id = f"alert-test-{suffix}"

        dialect = self.repository.dialect

        with self.repository.transaction() as session:
            session.execute(
                "INSERT INTO nodes(id, name, role, status) "
                f"VALUES ({dialect.parameters(4)})",
                (
                    self.node_id,
                    "Alert repository integration node",
                    "controller",
                    "active",
                ),
            )
            session.execute(
                "INSERT INTO controllers(id, node_id, name, status) "
                f"VALUES ({dialect.parameters(4)})",
                (
                    self.controller_id,
                    self.node_id,
                    "Alert repository integration controller",
                    "active",
                ),
            )

    def tearDown(self):
        placeholder = self.repository.dialect.placeholder

        with self.repository.transaction() as session:
            session.execute(
                "DELETE FROM alert_events "
                f"WHERE alert_id={placeholder}",
                (self.alert_id,),
            )
            session.execute(
                f"DELETE FROM alerts WHERE id={placeholder}",
                (self.alert_id,),
            )
            session.execute(
                "DELETE FROM controllers "
                f"WHERE id={placeholder}",
                (self.controller_id,),
            )
            session.execute(
                f"DELETE FROM nodes WHERE id={placeholder}",
                (self.node_id,),
            )

    def open_alert(self, level="WARNING"):
        return self.repository.open_alert(
            alert_id=self.alert_id,
            rule_id=f"rule.{self.alert_id}",
            level=level,
            message="Alert repository integration test",
            scope="controller",
            controller_id=self.controller_id,
        )

    def test_complete_alert_lifecycle(self):
        opened = self.open_alert()
        self.assertEqual(opened["action"], "OPEN")
        self.assertEqual(opened["state"], "OPEN")

        acknowledged = self.repository.acknowledge_alert(
            self.alert_id
        )
        self.assertEqual(
            acknowledged["state"],
            "ACKNOWLEDGED",
        )

        resolved = self.repository.resolve_alert(
            self.alert_id
        )
        self.assertEqual(resolved["state"], "RESOLVED")

        reopened = self.open_alert(level="CRITICAL")
        self.assertEqual(reopened["action"], "REOPEN")
        self.assertEqual(reopened["level"], "CRITICAL")

        suppressed = self.repository.suppress_alert(
            self.alert_id,
            10,
        )
        self.assertEqual(suppressed["state"], "SUPPRESSED")
        self.assertIsNotNone(suppressed["suppressed_until"])

        actions = [
            event["action"]
            for event in self.repository.alert_history(
                self.alert_id
            )
        ]
        self.assertEqual(
            actions,
            ["OPEN", "ACK", "RESOLVE", "REOPEN", "SUPPRESS"],
        )

    def test_filters_counts_and_pagination(self):
        self.open_alert(level="CRITICAL")

        alerts = self.repository.list_alerts(
            active_only=True,
            controller_id=self.controller_id,
            level="CRITICAL",
            limit=1,
            offset=0,
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["id"], self.alert_id)

        self.assertEqual(
            self.repository.count_alerts(
                active_only=True,
                controller_id=self.controller_id,
                level="CRITICAL",
            ),
            1,
        )

        self.repository.resolve_alert(self.alert_id)

        self.assertEqual(
            self.repository.count_alerts(
                active_only=True,
                controller_id=self.controller_id,
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
