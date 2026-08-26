#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, ROOT / "database", ROOT / "dashboard", RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from provisioning_contract import ProvisioningContractError, validate_provisioning_request
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from storage_pool_placement import select_storage_pool


def metadata(*pools):
    return json.dumps({"telemetry": {"storage_pools": list(pools)}})


def pool(pool_id, *, storage_class="ssd", enabled=True, health="online", priority=0,
         usable_bytes=1000, default=False):
    return {
        "id": pool_id,
        "root_path": f"/mnt/{pool_id}/instances",
        "storage_class": storage_class,
        "enabled": enabled,
        "health": health,
        "priority": priority,
        "usable_bytes": usable_bytes,
        "free_bytes": usable_bytes,
        "reserve_bytes": 0,
        "default": default,
    }


class StoragePoolSelectorTest(unittest.TestCase):
    def test_legacy_agent_returns_none(self):
        self.assertIsNone(select_storage_pool(None))
        self.assertIsNone(select_storage_pool(json.dumps({"telemetry": {}})))

    def test_filters_disabled_unhealthy_and_insufficient_pools(self):
        result = select_storage_pool(metadata(
            pool("disabled", enabled=False, priority=500, usable_bytes=9000),
            pool("offline", health="offline", priority=400, usable_bytes=9000),
            pool("small", priority=300, usable_bytes=50),
            pool("eligible", priority=10, usable_bytes=500),
        ), required_bytes=100)
        self.assertEqual(result["storage_pool_id"], "eligible")

    def test_class_preference_then_priority_and_capacity(self):
        result = select_storage_pool(metadata(
            pool("nvme-low", storage_class="nvme", priority=10, usable_bytes=9000),
            pool("ssd-high", storage_class="ssd", priority=500, usable_bytes=9000),
            pool("nvme-high-small", storage_class="nvme", priority=50, usable_bytes=1000),
            pool("nvme-high-large", storage_class="nvme", priority=50, usable_bytes=4000),
        ), preferred_storage_class="nvme")
        self.assertEqual(result["storage_pool_id"], "nvme-high-large")
        self.assertEqual(result["reason"], "storage_class_priority_capacity")

    def test_explicit_pool_is_strict(self):
        result = select_storage_pool(metadata(pool("nvme", priority=1), pool("ssd", priority=100)),
                                     requested_pool_id="nvme")
        self.assertEqual(result["storage_pool_id"], "nvme")
        self.assertEqual(result["source"], "explicit")
        with self.assertRaises(ValueError):
            select_storage_pool(metadata(pool("bad", enabled=False)), requested_pool_id="bad")
        with self.assertRaises(ValueError):
            select_storage_pool(metadata(pool("ssd", storage_class="ssd")), requested_pool_id="ssd",
                                preferred_storage_class="nvme")

    def test_deterministic_id_tiebreaker(self):
        result = select_storage_pool(metadata(pool("zeta", priority=10), pool("alpha", priority=10)))
        self.assertEqual(result["storage_pool_id"], "alpha")

    def test_active_reservations_reduce_effective_capacity(self):
        result = select_storage_pool(
            metadata(
                pool("nvme", priority=100, usable_bytes=5000),
                pool("hdd", priority=10, usable_bytes=10000),
            ),
            required_bytes=2000,
            reserved_bytes_by_pool={"nvme": 4000},
        )
        self.assertEqual(result["storage_pool_id"], "hdd")
        self.assertEqual(result["available_bytes"], 10000)
        with self.assertRaises(ValueError):
            select_storage_pool(
                metadata(pool("nvme", priority=100, usable_bytes=5000)),
                requested_pool_id="nvme", required_bytes=2000,
                reserved_bytes_by_pool={"nvme": 4000},
            )


class StoragePoolProvisioningIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="storage-controller")
        pairing = AgentPairingRepository(self.backend)
        issued = pairing.issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        pairing.enroll(
            pairing_token=issued.token,
            agent_id="agent-storage", node_id="node-storage", name="Storage Agent",
            fingerprint="sha256:storage-agent", hostname="storage-agent", os_name="linux", architecture="x86_64",
        )
        self.controller_id = str(identity["controller_id"])
        with self.backend.transaction() as conn:
            conn.execute("UPDATE agents SET status=?, metadata_json=? WHERE id=?", (
                "active",
                metadata(
                    pool("hdd", storage_class="hdd", priority=10, usable_bytes=10_000),
                    pool("nvme", storage_class="nvme", priority=100, usable_bytes=5_000, default=True),
                ),
                "agent-storage",
            ))
            conn.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                         (1, self.controller_id, "Customer", "active"))
            for instance_id, port_number in (("instance-storage", 24000), ("instance-storage-2", 24001)):
                conn.execute(
                    "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    (instance_id, "node-storage", "dayz", "dayz.stable", instance_id, "offline",
                     self.controller_id, "agent-storage", 1),
                )
                conn.execute("INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                             (instance_id, "node-storage", "game", "udp", port_number))
        self.jobs = AgentInstanceProvisioningRepository(self.backend)
        self.jobs.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _enqueue(self, instance_id="instance-storage", **extra):
        return self.jobs.enqueue(
            agent_id="agent-storage", instance_id=instance_id, environment_id="dayz.stable",
            selector="stable", selection={"game": "dayz", "provider": "steam"}, desired_state="running", **extra,
        )

    def test_repository_propagates_automatic_pool_to_instance_contract(self):
        state = self._enqueue()
        self.assertEqual(state["request"]["instance"]["storage_pool_id"], "nvme")

    def test_repository_respects_explicit_pool_and_legacy_fallback(self):
        state = self._enqueue(storage_pool_id="hdd")
        self.assertEqual(state["request"]["instance"]["storage_pool_id"], "hdd")
        with self.backend.transaction() as conn:
            conn.execute("UPDATE agent_instance_provisioning SET status='completed' WHERE provisioning_id=?",
                         (state["provisioning_id"],))
            conn.execute("UPDATE agents SET metadata_json=? WHERE id=?", (json.dumps({}), "agent-storage"))
        legacy = self._enqueue()
        self.assertNotIn("storage_pool_id", legacy["request"]["instance"])

    def test_active_job_reservation_prevents_pool_oversubscription(self):
        first = self._enqueue(required_storage_bytes=4000)
        self.assertEqual(first["request"]["instance"]["storage_pool_id"], "nvme")
        self.assertEqual(first["request"]["instance"]["storage_reserved_bytes"], 4000)

        second = self._enqueue(instance_id="instance-storage-2", required_storage_bytes=2000)
        self.assertEqual(second["request"]["instance"]["storage_pool_id"], "hdd")
        self.assertEqual(second["request"]["instance"]["storage_reserved_bytes"], 2000)

    def test_explicit_pool_rejects_capacity_already_reserved_by_active_job(self):
        self._enqueue(required_storage_bytes=4000)
        with self.assertRaises(ValueError):
            self._enqueue(instance_id="instance-storage-2", storage_pool_id="nvme", required_storage_bytes=2000)

    def test_final_result_releases_reservation_for_next_job(self):
        first = self._enqueue(required_storage_bytes=4000)
        self.jobs.apply_result("agent-storage", {
            "provisioning_id": first["provisioning_id"], "instance_id": "instance-storage",
            "status": "completed", "current_step": "completed", "progress": 100,
        })
        second = self._enqueue(instance_id="instance-storage-2", required_storage_bytes=2000)
        self.assertEqual(second["request"]["instance"]["storage_pool_id"], "nvme")

    def test_agent_contract_validates_capacity_reservation(self):
        state = self._enqueue(required_storage_bytes=1234)
        validated = validate_provisioning_request(state["request"], expected_agent_id="agent-storage")
        self.assertEqual(validated["instance"]["storage_reserved_bytes"], 1234)
        broken = dict(state["request"])
        broken["instance"] = dict(broken["instance"])
        broken["instance"].pop("storage_pool_id", None)
        with self.assertRaises(ProvisioningContractError):
            validate_provisioning_request(broken, expected_agent_id="agent-storage")


if __name__ == "__main__":
    unittest.main()
