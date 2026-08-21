#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_cli_auth import require_admin
from admin_management_repository import AdminManagementRepository
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from user_repository import UserRepository
from users import hash_password


class AdminDestructiveCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")
        ))
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="hybrid", hostname="delete-hybrid"
        )
        self.controller_id = str(identity["controller_id"])
        self.agent_id = str(identity["agent_id"])
        self.node_id = str(identity["node_id"])
        self.admin = AdminManagementRepository(self.backend)
        self.admin.initialize()
        users = UserRepository(self.backend)
        users.save(
            username="root-admin",
            password_hash=hash_password("strong-pass-1"),
            role="admin",
        )
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                ("customer-delete", self.controller_id, "Delete Customer", "active"),
            )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _create_contract_instance(self, contract_id: str, instance_id: str) -> None:
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit) VALUES (?,?,?,?,?)",
                (contract_id, "customer-delete", "dayz", "active", 2),
            )
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    instance_id, self.node_id, "dayz", "dayz.stable", "Delete Me", "offline",
                    self.controller_id, self.agent_id, "customer-delete",
                ),
            )
            connection.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES (?,?)",
                (instance_id, contract_id),
            )
            connection.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                (instance_id, self.node_id, "game", "udp", 24500),
            )

    def _complete_remove(self, instance_id: str, agent_id: str, requested_by="root-admin") -> None:
        queue = AgentInstanceRuntimeRepository(self.backend)
        command = queue.enqueue(
            agent_id=agent_id,
            instance_id=instance_id,
            action="remove",
            requested_by=requested_by,
        )
        queue.apply_result(agent_id, {
            "command_id": command["command_id"],
            "instance_id": instance_id,
            "action": "remove",
            "status": "completed",
            "result": {"removed": True},
        })

    def test_destructive_auth_requires_active_admin_credentials(self):
        with patch("admin_cli_auth.getpass.getpass", return_value="strong-pass-1"):
            actor = require_admin(self.backend, "root-admin")
        self.assertEqual(actor["role"], "admin")
        with self.assertRaises(PermissionError):
            require_admin(self.backend, "missing-admin")

    def test_instance_delete_releases_ports_but_preserves_active_contract(self):
        self._create_contract_instance("contract-keep", "instance-delete-one")
        state = self.admin.begin_instance_delete("instance-delete-one")
        self.assertEqual(state["status"], "deleting")
        self._complete_remove(state["instance_id"], state["agent_id"])
        with self.backend.connect() as connection:
            instance = connection.execute(
                "SELECT 1 FROM instances WHERE id=?", ("instance-delete-one",)
            ).fetchone()
            ports = connection.execute(
                "SELECT COUNT(*) AS total FROM instance_ports WHERE instance_id=?",
                ("instance-delete-one",),
            ).fetchone()
            contract = connection.execute(
                "SELECT status FROM service_contracts WHERE id=?", ("contract-keep",)
            ).fetchone()
        self.assertIsNone(instance)
        self.assertEqual(int(ports["total"]), 0)
        self.assertEqual(contract["status"], "active")

    def test_contract_delete_removes_all_instances_then_contract(self):
        self._create_contract_instance("contract-cascade", "instance-cascade-one")
        state = self.admin.begin_contract_delete("contract-cascade")
        self.assertEqual(state["status"], "deleting")
        self.assertEqual(len(state["instances"]), 1)
        item = state["instances"][0]
        self._complete_remove(item["instance_id"], item["agent_id"])
        with self.backend.connect() as connection:
            instance = connection.execute(
                "SELECT 1 FROM instances WHERE id=?", ("instance-cascade-one",)
            ).fetchone()
            contract = connection.execute(
                "SELECT 1 FROM service_contracts WHERE id=?", ("contract-cascade",)
            ).fetchone()
        self.assertIsNone(instance)
        self.assertIsNone(contract)


if __name__ == "__main__":
    unittest.main()
