#!/usr/bin/env python3

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (DATABASE, DASHBOARD):
    sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from infrastructure_api import infrastructure_for_user
from infrastructure_repository import InfrastructureRepository
from infrastructure_service import InfrastructureService


SCHEMA = """
CREATE TABLE controllers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL
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
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    controller_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE agent_locations (
    agent_id TEXT PRIMARY KEY,
    datacenter_id TEXT,
    public_host TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL
);
CREATE TABLE instances (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL
);
"""


class InfrastructureTopologyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "capivara.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO controllers(id, name, status) VALUES (?, ?, ?)",
            [
                ("controller-a", "Controller A", "active"),
                ("controller-b", "Controller B", "active"),
            ],
        )
        connection.execute(
            "INSERT INTO regions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("br-se", "Brasil Sudeste", "BR", "SA", -23.5, -46.6, "active"),
        )
        connection.execute(
            "INSERT INTO datacenters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("dc-sp", "br-se", "Sao Paulo", "demo", "Sao Paulo", "BR", -23.5, -46.6, "active"),
        )
        connection.executemany(
            "INSERT INTO agents VALUES (?, ?, ?, ?, ?)",
            [
                ("agent-a", "controller-a", "node-a", "Horizon", "active"),
                ("agent-unplaced", "controller-a", "node-u", "Unplaced", "active"),
                ("agent-b", "controller-b", "node-b", "Other", "active"),
            ],
        )
        connection.execute(
            "INSERT INTO agent_locations VALUES (?, ?, ?, ?, ?, ?)",
            ("agent-a", "dc-sp", "horizon.example", None, None, "active"),
        )
        connection.executemany(
            "INSERT INTO instances VALUES (?, ?)",
            [("instance-1", "agent-a"), ("instance-2", "agent-a")],
        )
        connection.commit()
        connection.close()

        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.database_path))
        )
        self.repository = InfrastructureRepository(self.backend)
        self.service = InfrastructureService(self.repository)

    def tearDown(self):
        self.temp.cleanup()

    def _execute(self, sql, params=()):
        connection = sqlite3.connect(self.database_path)
        connection.execute(sql, params)
        connection.commit()
        connection.close()

    def _placed_agent(self):
        tree = self.service.controller_tree("controller-a")
        return tree["children"][0]["children"][0]["children"][0]

    def test_repository_scopes_agents_and_counts_instances(self):
        agents = self.repository.agents(controller_id="controller-a")
        self.assertEqual({row["id"] for row in agents}, {"agent-a", "agent-unplaced"})
        self.assertEqual(
            self.repository.instance_counts_by_agent(controller_id="controller-a"),
            {"agent-a": 2},
        )

    def test_service_builds_geographic_tree_and_keeps_unplaced_agents(self):
        tree = self.service.controller_tree("controller-a")
        self.assertIsNotNone(tree)
        region = tree["children"][0]
        datacenter = region["children"][0]
        agent = datacenter["children"][0]
        self.assertEqual(region["id"], "br-se")
        self.assertEqual(datacenter["id"], "dc-sp")
        self.assertEqual(datacenter["region_id"], region["id"])
        self.assertEqual(agent["id"], "agent-a")
        self.assertEqual(agent["children_count"], 2)
        self.assertEqual(agent["topology_state"], "ready")
        self.assertTrue(agent["placement_ready"])
        self.assertEqual(tree["unplaced_agent_count"], 1)
        unplaced = tree["unplaced_agents"][0]
        self.assertEqual(unplaced["id"], "agent-unplaced")
        self.assertEqual(unplaced["topology_state"], "unconfigured")
        self.assertFalse(unplaced["placement_ready"])

    def test_inactive_controller_keeps_topology_ready_but_blocks_placement(self):
        self._execute(
            "UPDATE controllers SET status='disabled' WHERE id='controller-a'"
        )
        agent = self._placed_agent()
        self.assertEqual(agent["topology_state"], "ready")
        self.assertFalse(agent["placement_ready"])

    def test_offline_agent_keeps_topology_ready_but_blocks_placement(self):
        self._execute(
            "UPDATE agents SET status='offline' WHERE id='agent-a'"
        )
        agent = self._placed_agent()
        self.assertEqual(agent["topology_state"], "ready")
        self.assertFalse(agent["placement_ready"])

    def test_inactive_location_reports_partial_topology(self):
        self._execute(
            "UPDATE agent_locations SET status='disabled' WHERE agent_id='agent-a'"
        )
        agent = self._placed_agent()
        self.assertEqual(agent["topology_state"], "partial")
        self.assertFalse(agent["placement_ready"])

    def test_controller_role_cannot_expand_scope(self):
        user = {"role": "controller", "scope_id": "controller-a"}
        result = infrastructure_for_user(user, self.backend)
        self.assertEqual([item["id"] for item in result["controllers"]], ["controller-a"])
        with self.assertRaises(PermissionError):
            infrastructure_for_user(user, self.backend, controller_id="controller-b")

    def test_admin_can_view_all_controllers(self):
        result = infrastructure_for_user({"role": "admin"}, self.backend)
        self.assertEqual(
            {item["id"] for item in result["controllers"]},
            {"controller-a", "controller-b"},
        )

    def test_customer_cannot_view_administrative_topology(self):
        with self.assertRaises(PermissionError):
            infrastructure_for_user(
                {"role": "customer", "scope_id": "customer-a"},
                self.backend,
            )



    def test_decommissioned_agent_is_hidden_from_operational_list(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE agents SET status=? WHERE id=?",
                ("decommissioned", "agent-a"),
            )

        repository = InfrastructureRepository(self.backend)

        operational = repository.agents()
        operational_ids = {str(item["id"]) for item in operational}

        self.assertNotIn("agent-a", operational_ids)

        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT id,status FROM agents WHERE id=?",
                ("agent-a",),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(str(row["status"]), "decommissioned")

if __name__ == "__main__":
    unittest.main()
