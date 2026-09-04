#!/usr/bin/env python3
"""Tests for safe persisted infrastructure role transitions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from infrastructure_role_transition import (
    InfrastructureRoleTransitionError,
    demote_hybrid_to_controller,
    promote_controller_to_hybrid,
)
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class ControllerToHybridTransitionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "capivara.db"
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(self.db_path))
        )
        self.backend.initialize()
        self.repository = RegistryRepository(self.backend)
        self.identity = installation_profile_identity(
            self.repository,
            profile="controller",
            hostname="horizon-server",
        )
        self.node_id = str(self.identity["node_id"])
        self.controller_id = str(self.identity["controller_id"])
        self.agent_id = "agent-horizon-server"

        with self.backend.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO customers(controller_id,name,status,metadata_json) "
                "VALUES (?,?,?,?)",
                (
                    self.controller_id,
                    "Customer Preserved",
                    "active",
                    "{}",
                ),
            )
            self.customer_id = int(cursor.lastrowid)
            customer = connection.execute(
                "SELECT customer_code FROM customers WHERE id=?",
                (self.customer_id,),
            ).fetchone()
            self.customer_code = str(customer["customer_code"])
            connection.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    "contract-preserved",
                    self.customer_id,
                    "dayz",
                    "active",
                    1,
                    "{}",
                ),
            )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _promote(self):
        return promote_controller_to_hybrid(
            self.repository,
            node_id=self.node_id,
            controller_id=self.controller_id,
            agent_id=self.agent_id,
            agent_name="Agent horizon-server",
            region_id="region-local-horizon-server",
            region_name="Local",
            datacenter_id="datacenter-local-horizon-server",
            datacenter_name="Local Default",
        )

    def _demote(self):
        return demote_hybrid_to_controller(
            self.repository,
            node_id=self.node_id,
            controller_id=self.controller_id,
            agent_id=self.agent_id,
        )

    def _one(self, sql, params=()):
        with self.backend.connect() as connection:
            row = connection.execute(sql, params).fetchone()
            return None if row is None else dict(row)

    def test_promotes_existing_controller_and_preserves_owned_data(self):
        result = self._promote()

        self.assertTrue(result["changed"])
        self.assertEqual(result["previous_role"], "controller")
        self.assertEqual(result["node_role"], "hybrid")
        self.assertTrue(result["agent_created"])
        self.assertTrue(result["placement_identity_ready"])
        self.assertTrue(result["runtime_reconciliation_required"])

        node = self._one("SELECT id,role,status FROM nodes WHERE id=?", (self.node_id,))
        controller = self._one(
            "SELECT id,node_id,status FROM controllers WHERE id=?",
            (self.controller_id,),
        )
        agent = self._one(
            "SELECT id,controller_id,node_id,status FROM agents WHERE id=?",
            (self.agent_id,),
        )
        customer = self._one(
            "SELECT id,customer_code,controller_id,status FROM customers WHERE id=?",
            (self.customer_id,),
        )
        contract = self._one(
            "SELECT id,customer_id,status FROM service_contracts WHERE id=?",
            ("contract-preserved",),
        )

        self.assertEqual(node["role"], "hybrid")
        self.assertEqual(controller["node_id"], self.node_id)
        self.assertEqual(agent["controller_id"], self.controller_id)
        self.assertEqual(agent["node_id"], self.node_id)
        self.assertEqual(customer["controller_id"], self.controller_id)
        self.assertEqual(customer["customer_code"], self.customer_code)
        self.assertEqual(int(contract["customer_id"]), self.customer_id)

    def test_transition_is_idempotent(self):
        first = self._promote()
        second = self._promote()

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["previous_role"], "hybrid")
        self.assertFalse(second["agent_created"])

        with self.backend.connect() as connection:
            agent_count = connection.execute(
                "SELECT COUNT(*) AS total FROM agents WHERE node_id=?",
                (self.node_id,),
            ).fetchone()["total"]
            location_count = connection.execute(
                "SELECT COUNT(*) AS total FROM agent_locations WHERE agent_id=?",
                (self.agent_id,),
            ).fetchone()["total"]
        self.assertEqual(agent_count, 1)
        self.assertEqual(location_count, 1)

    def test_full_controller_hybrid_controller_hybrid_cycle(self):
        original_node_id = self.node_id
        original_controller_id = self.controller_id

        first_promotion = self._promote()
        demotion = self._demote()

        self.assertTrue(first_promotion["changed"])
        self.assertTrue(demotion["changed"])
        self.assertTrue(demotion["agent_removed"])
        self.assertEqual(demotion["previous_role"], "hybrid")
        self.assertEqual(demotion["node_role"], "controller")
        self.assertTrue(demotion["runtime_reconciliation_required"])

        node = self._one("SELECT id,role FROM nodes WHERE id=?", (self.node_id,))
        controller = self._one(
            "SELECT id,node_id,status FROM controllers WHERE id=?",
            (self.controller_id,),
        )
        agent = self._one("SELECT id FROM agents WHERE id=?", (self.agent_id,))
        location = self._one(
            "SELECT agent_id FROM agent_locations WHERE agent_id=?",
            (self.agent_id,),
        )
        customer = self._one(
            "SELECT controller_id FROM customers WHERE id=?",
            (self.customer_id,),
        )

        self.assertEqual(node["id"], original_node_id)
        self.assertEqual(node["role"], "controller")
        self.assertEqual(controller["id"], original_controller_id)
        self.assertEqual(controller["node_id"], original_node_id)
        self.assertIsNone(agent)
        self.assertIsNone(location)
        self.assertEqual(customer["controller_id"], original_controller_id)

        idempotent_demotion = self._demote()
        self.assertFalse(idempotent_demotion["changed"])
        self.assertFalse(idempotent_demotion["agent_removed"])
        self.assertFalse(idempotent_demotion["runtime_reconciliation_required"])

        second_promotion = self._promote()
        self.assertTrue(second_promotion["changed"])
        self.assertTrue(second_promotion["agent_created"])

        node_after = self._one("SELECT id,role FROM nodes WHERE id=?", (self.node_id,))
        controller_after = self._one(
            "SELECT id,node_id FROM controllers WHERE id=?",
            (self.controller_id,),
        )
        agent_after = self._one(
            "SELECT id,controller_id,node_id FROM agents WHERE id=?",
            (self.agent_id,),
        )
        self.assertEqual(node_after["id"], original_node_id)
        self.assertEqual(node_after["role"], "hybrid")
        self.assertEqual(controller_after["id"], original_controller_id)
        self.assertEqual(controller_after["node_id"], original_node_id)
        self.assertEqual(agent_after["controller_id"], original_controller_id)
        self.assertEqual(agent_after["node_id"], original_node_id)

    def test_demote_recovers_hybrid_role_when_local_agent_is_already_missing(self):
        self._promote()
        with self.backend.transaction() as connection:
            connection.execute("DELETE FROM agent_locations WHERE agent_id=?", (self.agent_id,))
            connection.execute("DELETE FROM agents WHERE id=?", (self.agent_id,))

        result = self._demote()

        self.assertTrue(result["changed"])
        self.assertFalse(result["agent_removed"])
        node = self._one("SELECT id,role FROM nodes WHERE id=?", (self.node_id,))
        controller = self._one(
            "SELECT id,node_id FROM controllers WHERE id=?",
            (self.controller_id,),
        )
        self.assertEqual(node["role"], "controller")
        self.assertEqual(controller["node_id"], self.node_id)

    def test_rejects_non_controller_node(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "UPDATE nodes SET role='agent' WHERE id=?",
                (self.node_id,),
            )

        with self.assertRaises(InfrastructureRoleTransitionError):
            self._promote()

    def test_rejects_controller_bound_to_another_node(self):
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("other-controller-node", "Other", "controller", "active"),
            )

        with self.assertRaises(InfrastructureRoleTransitionError):
            promote_controller_to_hybrid(
                self.repository,
                node_id="other-controller-node",
                controller_id=self.controller_id,
                agent_id="agent-other",
                agent_name="Agent Other",
                region_id="region-other",
                region_name="Other",
                datacenter_id="dc-other",
                datacenter_name="Other",
            )


if __name__ == "__main__":
    unittest.main()
