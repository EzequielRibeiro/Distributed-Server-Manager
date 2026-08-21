#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
for path in (ROOT, DATABASE):
    sys.path.insert(0, str(path))

from agent_lifecycle_repository import AgentLifecycleRepository, AgentNotFound
from backend import DatabaseConfig
from backend_factory import create_backend
from core.agent_lifecycle import InvalidAgentTransition
from core.events import EventPublisher, EventSeverity


SCHEMA = """
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    controller_id TEXT,
    status TEXT NOT NULL
);
"""


class AgentLifecycleRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"

        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO agents(id, controller_id, status) VALUES (?, ?, ?)",
            [
                ("agent-pending", "controller-a", "pending"),
                ("agent-active", "controller-a", "active"),
                ("agent-disabled", "controller-a", "disabled"),
            ],
        )
        connection.commit()
        connection.close()

        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(self.database_path),
            )
        )
        self.repository = AgentLifecycleRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_valid_transition_is_persisted(self):
        result = self.repository.transition("agent-pending", "pairing")

        self.assertTrue(result.changed)
        self.assertEqual(result.current, "pending")
        self.assertEqual(result.target, "pairing")
        self.assertEqual(self.repository.status("agent-pending"), "pairing")

    def test_idempotent_transition_does_not_change_state(self):
        result = self.repository.transition("agent-active", "active")

        self.assertFalse(result.changed)
        self.assertEqual(result.current, "active")
        self.assertEqual(result.target, "active")
        self.assertEqual(self.repository.status("agent-active"), "active")

    def test_invalid_transition_is_rejected_without_persisting(self):
        with self.assertRaises(InvalidAgentTransition):
            self.repository.transition("agent-disabled", "active")

        self.assertEqual(self.repository.status("agent-disabled"), "disabled")

    def test_reactivation_returns_to_pending(self):
        result = self.repository.transition("agent-disabled", "pending")

        self.assertTrue(result.changed)
        self.assertEqual(self.repository.status("agent-disabled"), "pending")

    def test_unknown_agent_is_rejected(self):
        with self.assertRaises(AgentNotFound):
            self.repository.transition("missing-agent", "pending")

    def test_failed_transition_rolls_back_transaction(self):
        with self.assertRaises(InvalidAgentTransition):
            self.repository.transition("agent-active", "pairing")

        self.assertEqual(self.repository.status("agent-active"), "active")

    def test_pairing_transition_publishes_scoped_event(self):
        received = []
        repository = AgentLifecycleRepository(
            self.backend,
            event_publisher=EventPublisher(sink=received.append),
        )

        repository.transition("agent-pending", "pairing")

        self.assertEqual(len(received), 1)
        event = received[0]
        self.assertEqual(event.type, "AGENT_PAIRING_STARTED")
        self.assertEqual(event.source.type, "agent")
        self.assertEqual(event.source.id, "agent-pending")
        self.assertEqual(event.scope.controller_id, "controller-a")
        self.assertEqual(event.scope.agent_id, "agent-pending")
        self.assertEqual(event.data["previous_status"], "pending")
        self.assertEqual(event.data["status"], "pairing")

    def test_offline_transition_uses_warning_severity(self):
        received = []
        repository = AgentLifecycleRepository(
            self.backend,
            event_publisher=EventPublisher(sink=received.append),
        )

        repository.transition("agent-active", "offline")

        self.assertEqual(received[0].type, "AGENT_OFFLINE")
        self.assertIs(received[0].severity, EventSeverity.WARNING)

    def test_idempotent_transition_does_not_publish_duplicate_event(self):
        received = []
        repository = AgentLifecycleRepository(
            self.backend,
            event_publisher=EventPublisher(sink=received.append),
        )

        repository.transition("agent-active", "active")

        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
