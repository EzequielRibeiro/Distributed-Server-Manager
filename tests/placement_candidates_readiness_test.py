#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
sys.path.insert(0, str(DATABASE))

from backend import DatabaseConfig
from backend_factory import create_backend
from location_repository import LocationRepository


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE controllers (id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE agents (id TEXT PRIMARY KEY, controller_id TEXT NOT NULL, node_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, FOREIGN KEY (controller_id) REFERENCES controllers(id));
CREATE TABLE regions (id TEXT PRIMARY KEY, name TEXT NOT NULL, country_code TEXT, continent_code TEXT, latitude REAL, longitude REAL, status TEXT NOT NULL);
CREATE TABLE datacenters (id TEXT PRIMARY KEY, region_id TEXT NOT NULL, name TEXT NOT NULL, provider TEXT, city TEXT, country_code TEXT, latitude REAL, longitude REAL, status TEXT NOT NULL, FOREIGN KEY (region_id) REFERENCES regions(id));
CREATE TABLE agent_locations (agent_id TEXT PRIMARY KEY, datacenter_id TEXT NOT NULL, latitude REAL, longitude REAL, public_host TEXT, status TEXT NOT NULL, FOREIGN KEY (agent_id) REFERENCES agents(id), FOREIGN KEY (datacenter_id) REFERENCES datacenters(id));
CREATE TABLE instances (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, FOREIGN KEY (agent_id) REFERENCES agents(id));
"""


class PlacementCandidatesReadinessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO controllers(id,name,status) VALUES (?,?,?)",
            ("controller-a", "Controller A", "active"),
        )
        connection.execute(
            "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
            ("agent-a", "controller-a", "node-a", "Agent A", "active"),
        )
        connection.execute(
            "INSERT INTO regions(id,name,status) VALUES (?,?,?)",
            ("br-se", "Brasil Sudeste", "active"),
        )
        connection.execute(
            "INSERT INTO datacenters(id,region_id,name,status) VALUES (?,?,?,?)",
            ("dc-sp", "br-se", "Sao Paulo", "active"),
        )
        connection.execute(
            "INSERT INTO agent_locations(agent_id,datacenter_id,status) VALUES (?,?,?)",
            ("agent-a", "dc-sp", "active"),
        )
        connection.commit()
        connection.close()

        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.repository = LocationRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _set_status(self, table, record_id, status):
        key = "agent_id" if table == "agent_locations" else "id"
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            f"UPDATE {table} SET status=? WHERE {key}=?",
            (status, record_id),
        )
        connection.commit()
        connection.close()

    def test_complete_active_chain_is_candidate(self):
        candidates = self.repository.candidates("controller-a")
        self.assertEqual([item["agent_id"] for item in candidates], ["agent-a"])

    def test_inactive_controller_excludes_agent(self):
        self._set_status("controllers", "controller-a", "disabled")
        self.assertEqual(self.repository.candidates("controller-a"), [])

    def test_inactive_agent_excludes_agent(self):
        self._set_status("agents", "agent-a", "offline")
        self.assertEqual(self.repository.candidates("controller-a"), [])

    def test_inactive_location_excludes_agent(self):
        self._set_status("agent_locations", "agent-a", "disabled")
        self.assertEqual(self.repository.candidates("controller-a"), [])

    def test_inactive_datacenter_excludes_agent(self):
        self._set_status("datacenters", "dc-sp", "disabled")
        self.assertEqual(self.repository.candidates("controller-a"), [])

    def test_inactive_region_excludes_agent(self):
        self._set_status("regions", "br-se", "disabled")
        self.assertEqual(self.repository.candidates("controller-a"), [])


if __name__ == "__main__":
    unittest.main()
