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


SCHEMA = """
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
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
            "INSERT INTO agents(id, status) VALUES (?, ?)",
            [
                ("agent-pending", "pending"),
                ("agent-active", "active"),
                ("agent-disabled", "disabled"),
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


if __name__ == "__main__":
    unittest.main()
