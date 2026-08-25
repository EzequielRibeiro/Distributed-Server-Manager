#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, ROOT / "database", ROOT / "dashboard", RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository
from runtime_health import project_instance_health
from runtime_limits import runtime_limits
from runtime_lock import RuntimeLockTimeout, instance_lock
from runtime_operations import read_operation, recover_interrupted_operations, runtime_operation


class RuntimeCompletionLocalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        self.old_instance_dir = instance_runtime.INSTANCE_DIR
        self.old_result_dir = instance_runtime.RESULT_DIR
        self.old_history_dir = instance_runtime.HISTORY_DIR
        instance_runtime.STATE_DIR = self.root / "state"
        instance_runtime.INSTANCE_DIR = instance_runtime.STATE_DIR / "instances"
        instance_runtime.RESULT_DIR = instance_runtime.STATE_DIR / "instance-results"
        instance_runtime.HISTORY_DIR = instance_runtime.STATE_DIR / "instance-command-history"
        self.config = {"agent_id": "agent-b12", "runtime_lock_timeout_seconds": 1}

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        instance_runtime.INSTANCE_DIR = self.old_instance_dir
        instance_runtime.RESULT_DIR = self.old_result_dir
        instance_runtime.HISTORY_DIR = self.old_history_dir
        self.temp.cleanup()

    def record(self, instance_id="instance-one", **extra):
        return instance_runtime.register_instance({
            "instance_id": instance_id, "agent_id": "agent-b12", "runtime_id": instance_id,
            "adapter": "systemd", "desired_state": "running", "observed_state": "running",
            "reconcile_status": "healthy", **extra,
        })

    def test_operation_journal_is_atomic_and_completed(self):
        self.record()
        with runtime_operation(self.config, "instance-one", "test", lock_timeout_seconds=1):
            running = read_operation("instance-one")
            self.assertEqual(running["status"], "running")
        completed = read_operation("instance-one")
        self.assertEqual(completed["status"], "completed")
        self.assertGreaterEqual(completed["duration_ms"], 0)

    def test_same_instance_mutations_are_serialized(self):
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def holder():
            with instance_lock("instance-one", "holder", timeout_seconds=1):
                entered.set()
                release.wait(2)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(RuntimeLockTimeout):
                with instance_lock("instance-one", "competitor", timeout_seconds=0.1):
                    pass
        except Exception as exc:
            errors.append(exc)
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(errors)

    def test_different_instances_do_not_block_each_other(self):
        with instance_lock("instance-one", "one", timeout_seconds=1):
            with instance_lock("instance-two", "two", timeout_seconds=0.1):
                pass

    def test_interrupted_operation_is_marked_after_agent_restart(self):
        path = instance_runtime.STATE_DIR / "instance-operations" / "instance-one.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "schema_version": 1, "kind": "CapivaraInstanceRuntimeOperation", "agent_id": "agent-b12",
            "instance_id": "instance-one", "operation": "provision", "status": "running",
        }), encoding="utf-8")
        recovered = recover_interrupted_operations(self.config)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(read_operation("instance-one")["status"], "interrupted")

    def test_final_health_contract(self):
        self.record()
        value = project_instance_health(self.config, "instance-one")
        self.assertEqual(value["kind"], "CapivaraInstanceRuntimeHealth")
        self.assertEqual(value["health"], "healthy")
        self.assertEqual(value["desired_state"], "running")
        self.assertEqual(value["observed_state"], "running")

    def test_operational_limits_are_bounded(self):
        limits = runtime_limits({"runtime_lock_timeout_seconds": 9999, "reconcile_max_retries": 0})
        self.assertEqual(limits.lock_timeout_seconds, 60)
        self.assertEqual(limits.max_reconcile_retries, 1)


class RuntimeHealthProjectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="b12-controller")
        issued = AgentPairingRepository(self.backend).issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        status, enrolled = dispatch_enroll({
            "pairing_token": issued.token, "agent_id": "agent-b12", "node_id": "node-b12", "name": "B12 Agent",
            "fingerprint": "sha256:b12-agent", "hostname": "b12-agent", "os": "linux", "architecture": "x86_64",
        }, backend=self.backend)
        self.assertEqual(status, 201)
        self.controller_id = enrolled["controller_id"]
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:b12-agent",
        }
        status, _ = dispatch_heartbeat({"agent_id": "agent-b12"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", (1, self.controller_id, "Customer", "active"))
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-b12", "node-b12", "dayz", "dayz.stable", "Instance B12", "offline", self.controller_id, "agent-b12", 1),
            )
        self.repo = AgentInstanceRuntimeHealthRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_heartbeat_persists_only_owned_health_projection(self):
        status, _ = dispatch_heartbeat({
            "agent_id": "agent-b12",
            "instance_runtime_health": [{
                "instance_id": "instance-b12", "desired_state": "running", "observed_state": "running",
                "reconcile_status": "healthy", "health": "healthy", "operation_status": "idle",
            }, {"instance_id": "missing", "health": "healthy"}],
        }, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        rows = self.repo.list_for_agent("agent-b12")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["health"], "healthy")
        self.assertEqual(rows[0]["operation_status"], "idle")


if __name__ == "__main__":
    unittest.main()
