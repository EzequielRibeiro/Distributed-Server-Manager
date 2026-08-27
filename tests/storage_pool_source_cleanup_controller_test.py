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

from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from agent_heartbeat_api import record_agent_heartbeat
from instance_storage_pool_migration_repository import CLEANUP_OPERATION_TYPE, InstanceStoragePoolMigrationRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


def pool(pool_id: str, *, usable_bytes: int, default: bool = False) -> dict:
    return {
        "id": pool_id,
        "root_path": f"/mnt/{pool_id}/instances",
        "storage_class": "standard",
        "enabled": True,
        "health": "online",
        "priority": 10,
        "usable_bytes": usable_bytes,
        "free_bytes": usable_bytes,
        "reserve_bytes": 0,
        "default": default,
    }


class StoragePoolSourceCleanupControllerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="cleanup-controller")
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
            "telemetry": {"storage_pools": [pool("hdd", usable_bytes=20_000, default=True), pool("nvme", usable_bytes=20_000)]},
            "instance_telemetry": [{"instance_id": "instance-one", "storage_pool_id": "hdd", "storage_used_bytes": 4_000}],
        }
        with self.backend.transaction() as conn:
            conn.execute("UPDATE agents SET status=?, metadata_json=? WHERE id=?", ("active", json.dumps(metadata), "agent-storage"))
            conn.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", (1, self.controller_id, "Customer", "active"))
            conn.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-one", "node-storage", "dayz", "dayz.stable", "instance-one", "offline", self.controller_id, "agent-storage", 1),
            )
        self.repo = InstanceStoragePoolMigrationRepository(self.backend)
        self.repo.initialize()
        migration = self.repo.enqueue(instance_id="instance-one", target_storage_pool_id="nvme", requested_by="admin")
        self.migration_id = migration["migration_id"]
        self.repo.apply_result(
            "agent-storage",
            {
                "migration_id": self.migration_id,
                "instance_id": "instance-one",
                "status": "completed",
                "current_step": "completed",
                "progress": 100,
                "verified_files": 2,
                "verified_bytes": 4_000,
                "source_preserved": True,
            },
        )
        metadata["instance_telemetry"][0]["storage_pool_id"] = "nvme"
        with self.backend.transaction() as conn:
            conn.execute("UPDATE agents SET metadata_json=? WHERE id=?", (json.dumps(metadata), "agent-storage"))

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_preview_requires_current_target_assignment(self):
        preview = self.repo.cleanup_preview(self.migration_id)
        self.assertTrue(preview["eligible"])
        self.assertEqual(preview["source_storage_pool_id"], "hdd")
        self.assertEqual(preview["target_storage_pool_id"], "nvme")
        self.assertEqual(preview["confirmation_required"], self.migration_id)

    def test_cleanup_requires_exact_migration_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmation"):
            self.repo.enqueue_cleanup(source_migration_id=self.migration_id, confirmation="wrong", requested_by="admin")

    def test_cleanup_uses_same_authenticated_heartbeat_queue(self):
        cleanup = self.repo.enqueue_cleanup(
            source_migration_id=self.migration_id,
            confirmation=self.migration_id,
            requested_by="admin",
        )
        self.assertEqual(cleanup["operation_type"], CLEANUP_OPERATION_TYPE)
        response = record_agent_heartbeat("agent-storage", {"agent_id": "agent-storage"}, backend=self.backend)
        command = response["storage_pool_migration_command"]
        self.assertEqual(command["action"], "cleanup-source")
        self.assertEqual(command["source_migration_id"], self.migration_id)
        self.assertNotIn("source_path", command)
        self.assertEqual(self.repo.snapshot(cleanup["migration_id"])["status"], "delivered")

        response = record_agent_heartbeat(
            "agent-storage",
            {
                "agent_id": "agent-storage",
                "storage_pool_migration_result": {
                    "migration_id": cleanup["migration_id"],
                    "instance_id": "instance-one",
                    "status": "completed",
                    "current_step": "completed",
                    "progress": 100,
                    "removed_files": 2,
                    "removed_bytes": 4_000,
                },
            },
            backend=self.backend,
        )
        self.assertEqual(response["storage_pool_migration_state"]["status"], "completed")
        self.assertEqual(self.repo.snapshot(cleanup["migration_id"])["status"], "completed")

    def test_completed_cleanup_is_idempotent(self):
        first = self.repo.enqueue_cleanup(source_migration_id=self.migration_id, confirmation=self.migration_id, requested_by="admin")
        self.repo.apply_result(
            "agent-storage",
            {"migration_id": first["migration_id"], "instance_id": "instance-one", "status": "completed", "progress": 100},
        )
        second = self.repo.enqueue_cleanup(source_migration_id=self.migration_id, confirmation=self.migration_id, requested_by="admin")
        self.assertEqual(second["migration_id"], first["migration_id"])
        self.assertEqual(second["status"], "completed")


if __name__ == "__main__":
    unittest.main()
