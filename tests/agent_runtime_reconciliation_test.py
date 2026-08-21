#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, ROOT / "database", ROOT / "dashboard", RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
import runtime_reconciler
from agent_instance_reconciliation_repository import AgentInstanceReconciliationRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class FakeMaterializer:
    def __init__(self, state):
        self.state = dict(state)

    def inspect(self, spec):
        return dict(self.state)


class FakeAdapter:
    def __init__(self, running=False):
        self.running = running

    def status(self, spec):
        return {
            "available": True,
            "running": self.running,
            "active_state": "active" if self.running else "inactive",
            "sub_state": "running" if self.running else "dead",
        }


class RuntimeReconcilerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        self.old_instance = instance_runtime.INSTANCE_DIR
        self.old_result = instance_runtime.RESULT_DIR
        self.old_history = instance_runtime.HISTORY_DIR
        instance_runtime.STATE_DIR = self.root / "state"
        instance_runtime.INSTANCE_DIR = instance_runtime.STATE_DIR / "instances"
        instance_runtime.RESULT_DIR = instance_runtime.STATE_DIR / "instance-results"
        instance_runtime.HISTORY_DIR = instance_runtime.STATE_DIR / "instance-command-history"
        self.config = {
            "agent_id": "agent-one",
            "reconcile_failure_threshold": 2,
            "reconcile_base_backoff_seconds": 1,
            "reconcile_max_backoff_seconds": 4,
        }
        work = self.root / "serverfiles"; work.mkdir()
        self.record = instance_runtime.register_instance({
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "instance-one",
            "adapter": "systemd",
            "working_directory": str(work),
            "executable": str(work / "server"),
            "arguments": [],
            "environment": {},
            "user": "capivara-instance",
            "desired_state": "running",
            "observed_state": "stopped",
        })
        self.old_materializer = runtime_reconciler.resolve_materializer
        self.old_adapter = runtime_reconciler.resolve_adapter
        self.old_privileged = runtime_reconciler.privileged_materialization.materialize
        self.old_reconcile = runtime_reconciler.runtime_materialization.reconcile

    def tearDown(self):
        runtime_reconciler.resolve_materializer = self.old_materializer
        runtime_reconciler.resolve_adapter = self.old_adapter
        runtime_reconciler.privileged_materialization.materialize = self.old_privileged
        runtime_reconciler.runtime_materialization.reconcile = self.old_reconcile
        instance_runtime.STATE_DIR = self.old_state
        instance_runtime.INSTANCE_DIR = self.old_instance
        instance_runtime.RESULT_DIR = self.old_result
        instance_runtime.HISTORY_DIR = self.old_history
        self.temp.cleanup()

    def test_dead_process_is_recovered_to_desired_running_state(self):
        runtime_reconciler.resolve_materializer = lambda spec: FakeMaterializer({"exists": True, "owned": True, "matches": True})
        runtime_reconciler.resolve_adapter = lambda spec: FakeAdapter(False)
        runtime_reconciler.runtime_materialization.reconcile = lambda config, instance_id: {"observed_state": "running"}
        result = runtime_reconciler.reconcile_instance(self.config, "instance-one")
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["recovered"])
        self.assertEqual(result["action"], "start")
        saved = instance_runtime.get_instance("instance-one")
        self.assertEqual(saved["reconcile_status"], "healthy")
        self.assertEqual(saved["reconcile_retry_count"], 0)

    def test_missing_owned_runtime_is_rematerialized_before_reconcile(self):
        runtime_reconciler.resolve_materializer = lambda spec: FakeMaterializer({"exists": False, "owned": False, "matches": False})
        calls = []
        runtime_reconciler.privileged_materialization.materialize = lambda config, spec: calls.append(spec["instance_id"]) or {"operation": {"changed": True}}
        runtime_reconciler.resolve_adapter = lambda spec: FakeAdapter(True)
        runtime_reconciler.runtime_materialization.reconcile = lambda config, instance_id: {"observed_state": "running"}
        result = runtime_reconciler.reconcile_instance(self.config, "instance-one")
        self.assertEqual(calls, ["instance-one"])
        self.assertTrue(result["recovered"])
        self.assertEqual(result["status"], "healthy")

    def test_ownership_violation_is_never_auto_repaired_and_degrades_after_threshold(self):
        runtime_reconciler.resolve_materializer = lambda spec: FakeMaterializer({"exists": True, "owned": False, "matches": False})
        calls = []
        runtime_reconciler.privileged_materialization.materialize = lambda config, spec: calls.append(spec["instance_id"])
        first = runtime_reconciler.reconcile_instance(self.config, "instance-one", force=True)
        second = runtime_reconciler.reconcile_instance(self.config, "instance-one", force=True)
        self.assertEqual(first["status"], "retry_wait")
        self.assertEqual(second["status"], "degraded")
        self.assertEqual(second["drift"], "ownership_violation")
        self.assertEqual(calls, [])

    def test_backoff_skips_until_next_retry(self):
        runtime_reconciler.resolve_materializer = lambda spec: (_ for _ in ()).throw(RuntimeError("inspect failed"))
        failed = runtime_reconciler.reconcile_instance(self.config, "instance-one", force=True)
        skipped = runtime_reconciler.reconcile_instance(self.config, "instance-one")
        self.assertEqual(failed["status"], "retry_wait")
        self.assertTrue(skipped["skipped"])

    def test_reconciliation_inventory_exposes_controller_projection_fields(self):
        runtime_reconciler.resolve_materializer = lambda spec: FakeMaterializer({"exists": True, "owned": True, "matches": True})
        runtime_reconciler.resolve_adapter = lambda spec: FakeAdapter(True)
        runtime_reconciler.runtime_materialization.reconcile = lambda config, instance_id: {"observed_state": "running"}
        runtime_reconciler.reconcile_instance(self.config, "instance-one")
        inventory = runtime_reconciler.reconciliation_inventory(self.config)
        self.assertEqual(inventory[0]["reconcile_status"], "healthy")
        self.assertEqual(inventory[0]["observed_state"], "running")


class ControllerProjectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="b11-controller")
        issued = AgentPairingRepository(self.backend).issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        status, enrolled = dispatch_enroll({
            "pairing_token": issued.token,
            "agent_id": "agent-b11",
            "node_id": "node-b11",
            "name": "B11 Agent",
            "fingerprint": "sha256:b11-agent",
            "hostname": "b11-agent",
            "os": "linux",
            "architecture": "x86_64",
        }, backend=self.backend)
        self.assertEqual(status, 201)
        self.controller_id = enrolled["controller_id"]
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:b11-agent",
        }
        status, _ = dispatch_heartbeat({"agent_id": "agent-b11"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        with self.backend.transaction() as conn:
            conn.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", ("customer-b11", self.controller_id, "Customer", "active"))
            conn.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-b11", "node-b11", "dayz", "dayz.stable", "Instance B11", "offline", self.controller_id, "agent-b11", "customer-b11"),
            )

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    def test_heartbeat_persists_reconciliation_projection(self):
        status, _ = dispatch_heartbeat({
            "agent_id": "agent-b11",
            "instance_reconciliation": [{
                "instance_id": "instance-b11",
                "desired_state": "running",
                "observed_state": "running",
                "reconcile_status": "healthy",
                "retry_count": 0,
                "last_attempt_at": "2026-08-21T16:00:00Z",
                "last_success_at": "2026-08-21T16:00:00Z",
            }],
        }, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        rows = AgentInstanceReconciliationRepository(self.backend).list_for_agent("agent-b11")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reconcile_status"], "healthy")
        self.assertEqual(rows[0]["observed_state"], "running")


if __name__ == "__main__":
    unittest.main()
