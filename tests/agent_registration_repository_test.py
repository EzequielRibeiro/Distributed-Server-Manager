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

from agent_registration_repository import (
    AgentRegistrationConflict,
    AgentRegistrationRepository,
    ControllerInactive,
    ControllerNotFound,
)
from backend import DatabaseConfig
from backend_factory import create_backend


SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE controllers (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    node_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


class AgentRegistrationRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
            [
                ("controller-a", "controller-node-a", "Controller A", "active"),
                ("controller-disabled", "controller-node-d", "Disabled", "disabled"),
            ],
        )
        connection.commit()
        connection.close()

        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.repository = AgentRegistrationRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _row(self, table, identifier):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                f"SELECT * FROM {table} WHERE id=?", (identifier,)
            ).fetchone()
        finally:
            connection.close()

    def test_registers_node_and_agent_as_pending(self):
        result = self.repository.register(
            controller_id="controller-a",
            agent_id="agent-a",
            node_id="node-a",
            name="Agent A",
        )

        self.assertEqual(result.status, "pending")
        self.assertEqual(self._row("nodes", "node-a")["status"], "pending")
        agent = self._row("agents", "agent-a")
        self.assertEqual(agent["status"], "pending")
        self.assertEqual(agent["controller_id"], "controller-a")

    def test_unknown_controller_is_rejected_without_partial_insert(self):
        with self.assertRaises(ControllerNotFound):
            self.repository.register(
                controller_id="missing",
                agent_id="agent-a",
                node_id="node-a",
                name="Agent A",
            )
        self.assertIsNone(self._row("nodes", "node-a"))
        self.assertIsNone(self._row("agents", "agent-a"))

    def test_inactive_controller_is_rejected(self):
        with self.assertRaises(ControllerInactive):
            self.repository.register(
                controller_id="controller-disabled",
                agent_id="agent-a",
                node_id="node-a",
                name="Agent A",
            )
        self.assertIsNone(self._row("nodes", "node-a"))

    def test_duplicate_agent_identity_is_rejected_atomically(self):
        self.repository.register(
            controller_id="controller-a",
            agent_id="agent-a",
            node_id="node-a",
            name="Agent A",
        )

        with self.assertRaises(AgentRegistrationConflict):
            self.repository.register(
                controller_id="controller-a",
                agent_id="agent-a",
                node_id="node-b",
                name="Duplicate Agent",
            )
        self.assertIsNone(self._row("nodes", "node-b"))

    def test_duplicate_node_identity_is_rejected(self):
        self.repository.register(
            controller_id="controller-a",
            agent_id="agent-a",
            node_id="node-a",
            name="Agent A",
        )

        with self.assertRaises(AgentRegistrationConflict):
            self.repository.register(
                controller_id="controller-a",
                agent_id="agent-b",
                node_id="node-a",
                name="Agent B",
            )
        self.assertIsNone(self._row("agents", "agent-b"))


if __name__ == "__main__":
    unittest.main()
