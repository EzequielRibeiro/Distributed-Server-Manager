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
    pairing_action_for_user,
    register_agent_for_user,
    transition_agent_for_user,
)
from backend import DatabaseConfig
from backend_factory import create_backend
from location_repository import LocationRepository


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
CREATE TABLE regions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    continent_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL
);
CREATE TABLE datacenters (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT,
    city TEXT,
    country_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL
);
CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY,
    datacenter_id TEXT,
    latitude REAL,
    longitude REAL,
    public_host TEXT,
    status TEXT NOT NULL
);
CREATE TABLE instances (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL
);
"""


class AgentPhase2IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
            ("controller-a", "controller-node-a", "Controller A", "active"),
        )
        connection.execute(
            "INSERT INTO regions VALUES (?,?,?,?,?,?,?)",
            ("br-se", "Brasil Sudeste", "BR", "SA", -23.5, -46.6, "active"),
        )
        connection.execute(
            "INSERT INTO datacenters VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "dc-sp",
                "br-se",
                "Sao Paulo",
                "demo",
                "Sao Paulo",
                "BR",
                -23.5,
                -46.6,
                "active",
            ),
        )
        connection.commit()
        connection.close()

        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.user = {"role": "controller", "scope_id": "controller-a"}
        self.locations = LocationRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_registration_pairing_topology_and_offline_gate_placement(self):
        registered = register_agent_for_user(
            self.user,
            self.backend,
            {"agent_id": "agent-a", "node_id": "node-a", "name": "Agent A"},
        )
        self.assertEqual(registered["status"], "pending")

        self.locations.upsert_agent_location(
            agent_id="agent-a",
            datacenter_id="dc-sp",
            public_host="agent-a.example",
            status="active",
        )
        self.assertEqual(self.locations.candidates("controller-a"), [])

        pairing_action_for_user(
            self.user,
            self.backend,
            {"agent_id": "agent-a", "action": "start"},
        )
        self.assertEqual(self.locations.candidates("controller-a"), [])

        approved = pairing_action_for_user(
            self.user,
            self.backend,
            {"agent_id": "agent-a", "action": "approve"},
        )
        self.assertEqual(approved["status"], "active")

        candidates = self.locations.candidates("controller-a")
        self.assertEqual([item["agent_id"] for item in candidates], ["agent-a"])

        offline = transition_agent_for_user(
            self.user,
            self.backend,
            {"agent_id": "agent-a", "target": "offline"},
        )
        self.assertEqual(offline["status"], "offline")
        self.assertEqual(self.locations.candidates("controller-a"), [])

        active_again = transition_agent_for_user(
            self.user,
            self.backend,
            {"agent_id": "agent-a", "target": "active"},
        )
        self.assertEqual(active_again["status"], "active")
        self.assertEqual(
            [item["agent_id"] for item in self.locations.candidates("controller-a")],
            ["agent-a"],
        )


if __name__ == "__main__":
    unittest.main()
