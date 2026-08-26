#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_admin_http import _authorize
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from agent_heartbeat_api import record_agent_heartbeat
from instance_storage_pool_migration_repository import InstanceStoragePoolMigrationRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


def pool(pool_id: str, *, usable_bytes: int, default: bool = False, enabled: bool = True) -> dict:
    return {
        "id": pool_id,
        "root_path": f"/mnt/{pool_id}/instances",
        "storage_class": "nvme" if pool_id == "nvme" else "capacity",
        "enabled": enabled,
        "health": "online",
        "priority": 100 if pool_id == "nvme" else 10,
        "usable_bytes": usable_bytes,
        "free_bytes": usable_bytes,
        "reserve_bytes": 0,
        "default": default,
    }


class StoragePoolMigrationControllerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="migration-controller"
        )
        self.controller_id = str(identity["controller_id"])
        pairing = AgentPairingRepository(self.backend)
        issued = pairing.issue_token(controller_id=self.controller_id, ttl_seconds=300)
        pairing.enroll(
            pairing_token=issued.token,
            agent_id="agent-storage",
            node_id="node-storage",
            name="Storage Agent",
            fingerprint="sha256:storage-agent",
            hostname="storage-agent",
            os_name="linux",
            architecture="x86_64",
        )
        metadata = {
            "telemetry": {
                "storage_pools": [
                    pool("hdd", usable_bytes=20_000, default=True),
                    pool("nvme", usable_bytes=5_000),
                ]
            },
            "instance_telemetry": [
                {"instance_id": "instance-one", "storage_pool_id": "hdd", "storage_used_bytes": 4_000},
                {"instance_id": "instance-two", "storage_pool_id": "hdd", "storage_used_bytes": 2_000},
            ],
        }
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE agents SET status=?, metadata_json=? WHERE id=?",
                ("active", json.dumps(metadata), "agent-storage"),
            )
            conn.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                (1, self.controller_id, "Customer", "active"),
            )
            for instance_id in ("instance-one", "instance-two"):
                conn.execute(
                    "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        instance_id,
                        "node-storage",
                        "dayz",
                        "dayz.stable",
                        instance_id,
                        "offline",
                        self.controller_id,
                        "agent-storage",
                        1,
                    ),
                )
        self.repo = InstanceStoragePoolMigrationRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_enqueue_uses_agent_reported_source_and_private_size(self):
        state = self.repo.enqueue(
            instance_id="instance-one",
            target_storage_pool_id="nvme",
            requested_by="admin",
        )
        self.assertEqual(state["status"], "queued")
        self.assertEqual(state["request"]["source_storage_pool_id"], "hdd")
        self.assertEqual(state["request"]["target_storage_pool_id"], "nvme")
        self.assertEqual(state["request"]["required_storage_bytes"], 4_000)
        self.assertEqual(self.repo.agent_for_instance("instance-one"), "agent-storage")

    def test_active_migration_reservation_prevents_oversubscription(self):
        first = self.repo.enqueue(instance_id="instance-one", target_storage_pool_id="nvme", requested_by="admin")
        self.assertEqual(first["status"], "queued")
        with self.assertRaises(ValueError):
            self.repo.enqueue(instance_id="instance-two", target_storage_pool_id="nvme", requested_by="admin")

        self.repo.apply_result(
            "agent-storage",
            {
                "migration_id": first["migration_id"],
                "instance_id": "instance-one",
                "status": "completed",
                "current_step": "completed",
                "progress": 100,
                "verified_files": 2,
                "verified_bytes": 4_000,
                "source_preserved": True,
            },
        )
        second = self.repo.enqueue(instance_id="instance-two", target_storage_pool_id="nvme", requested_by="admin")
        self.assertEqual(second["status"], "queued")

    def test_heartbeat_delivers_command_and_accepts_final_result(self):
        queued = self.repo.enqueue(instance_id="instance-one", target_storage_pool_id="nvme", requested_by="admin")
        response = record_agent_heartbeat("agent-storage", {"agent_id": "agent-storage"}, backend=self.backend)
        command = response["storage_pool_migration_command"]
        self.assertEqual(command["migration_id"], queued["migration_id"])
        self.assertEqual(command["source_storage_pool_id"], "hdd")
        self.assertEqual(command["target_storage_pool_id"], "nvme")
        self.assertEqual(self.repo.snapshot(queued["migration_id"])["status"], "delivered")

        response = record_agent_heartbeat(
            "agent-storage",
            {
                "agent_id": "agent-storage",
                "storage_pool_migration_result": {
                    "migration_id": queued["migration_id"],
                    "instance_id": "instance-one",
                    "status": "completed",
                    "current_step": "completed",
                    "progress": 100,
                    "verified_files": 3,
                    "verified_bytes": 4_000,
                    "source_preserved": True,
                },
            },
            backend=self.backend,
        )
        self.assertIsNone(response["storage_pool_migration_command"])
        self.assertEqual(response["storage_pool_migration_state"]["status"], "completed")
        self.assertEqual(self.repo.snapshot(queued["migration_id"])["status"], "completed")

    def test_result_identity_mismatch_is_rejected(self):
        queued = self.repo.enqueue(instance_id="instance-one", target_storage_pool_id="nvme", requested_by="admin")
        with self.assertRaises(PermissionError):
            self.repo.apply_result(
                "another-agent",
                {
                    "migration_id": queued["migration_id"],
                    "instance_id": "instance-one",
                    "status": "completed",
                    "progress": 100,
                },
            )
        with self.assertRaises(ValueError):
            self.repo.apply_result(
                "agent-storage",
                {
                    "migration_id": queued["migration_id"],
                    "instance_id": "instance-two",
                    "status": "completed",
                    "progress": 100,
                },
            )

    def test_controller_scope_authorization_is_enforced(self):
        detail = {"controller_id": self.controller_id}
        _authorize({"role": "admin", "username": "admin"}, detail)
        _authorize({"role": "controller", "scope_id": self.controller_id}, detail)
        with self.assertRaises(PermissionError):
            _authorize({"role": "controller", "scope_id": "different-controller"}, detail)
        with self.assertRaises(PermissionError):
            _authorize({"role": "operator"}, detail)


if __name__ == "__main__":
    unittest.main()
