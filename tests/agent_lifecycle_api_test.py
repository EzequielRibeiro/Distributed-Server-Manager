#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    sys.path.insert(0, str(path))

from agent_lifecycle_api import (
    agent_lifecycle_for_user,
    pairing_action_for_user,
    register_agent_for_user,
)
from backend import DatabaseConfig
from backend_factory import create_backend
from core.agent_lifecycle import InvalidAgentTransition


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
CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY,
    datacenter_id TEXT,
    latitude REAL,
    longitude REAL,
    public_host TEXT,
    status TEXT NOT NULL
);
"""


class AgentLifecycleApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
            [
                ("controller-a", "controller-node-a", "Controller A", "active"),
                ("controller-b", "controller-node-b", "Controller B", "active"),
            ],
        )
        connection.commit()
        connection.close()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.controller_user = {"role": "controller", "scope_id": "controller-a"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_controller_registers_agent_in_own_scope(self):
        result = register_agent_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "node_id": "node-a", "name": "Agent A"},
        )

        self.assertEqual(result["controller_id"], "controller-a")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(
            result["allowed_transitions"],
            ["disabled", "pairing", "rejected"],
        )

    def test_controller_cannot_register_under_other_controller(self):
        with self.assertRaises(PermissionError):
            register_agent_for_user(
                self.controller_user,
                self.backend,
                {
                    "controller_id": "controller-b",
                    "agent_id": "agent-a",
                    "node_id": "node-a",
                    "name": "Agent A",
                },
            )

    def test_customer_cannot_register_agent(self):
        with self.assertRaises(PermissionError):
            register_agent_for_user(
                {"role": "customer", "scope_id": "customer-a"},
                self.backend,
                {"agent_id": "agent-a", "node_id": "node-a", "name": "Agent A"},
            )

    def test_pairing_start_then_approve_activates_agent(self):
        register_agent_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "node_id": "node-a", "name": "Agent A"},
        )

        started = pairing_action_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "action": "start"},
        )
        self.assertEqual(started["previous_status"], "pending")
        self.assertEqual(started["status"], "pairing")

        approved = pairing_action_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "action": "approve"},
        )
        self.assertEqual(approved["previous_status"], "pairing")
        self.assertEqual(approved["status"], "active")

    def test_pairing_rejection_is_persisted(self):
        register_agent_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "node_id": "node-a", "name": "Agent A"},
        )
        pairing_action_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "action": "start"},
        )
        rejected = pairing_action_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "action": "reject"},
        )
        self.assertEqual(rejected["status"], "rejected")

    def test_approve_without_pairing_is_rejected(self):
        register_agent_for_user(
            self.controller_user,
            self.backend,
            {"agent_id": "agent-a", "node_id": "node-a", "name": "Agent A"},
        )
        with self.assertRaises(InvalidAgentTransition):
            pairing_action_for_user(
                self.controller_user,
                self.backend,
                {"agent_id": "agent-a", "action": "approve"},
            )

    def test_lifecycle_query_respects_controller_scope(self):
        register_agent_for_user(
            {"role": "admin"},
            self.backend,
            {
                "controller_id": "controller-b",
                "agent_id": "agent-b",
                "node_id": "node-b",
                "name": "Agent B",
            },
        )
        with self.assertRaises(PermissionError):
            agent_lifecycle_for_user(
                self.controller_user,
                self.backend,
                "agent-b",
            )


if __name__ == "__main__":
    unittest.main()
