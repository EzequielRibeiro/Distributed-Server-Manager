#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, ROOT / "database", ROOT / "dashboard", RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from backend import DatabaseConfig
from backend_factory import create_backend
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
                entered.set(); release.wait(2)

        thread = threading.Thread(target=holder)
        thread.start(); self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(RuntimeLockTimeout):
                with instance_lock("instance-one", "competitor", timeout_seconds=0.1):
                    pass
        except Exception as exc:
            errors.append(exc)
        finally:
            release.set(); thread.join(2)
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
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO controllers(id,name,mode) VALUES (?,?,?)", ("controller-b12", "B12", "controller"))
            connection.execute("INSERT INTO nodes(id,controller_id,name) VALUES (?,?,?)", ("node-b12", "controller-b12", "Node"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-b12", "controller-b12", "node-b12", "Agent", "active"))
            connection.execute("INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id) VALUES (?,?,?,?,?,?,?,?)", ("instance-b12", "node-b12", "dayz", "dayz.stable", "Instance", "online", "controller-b12", "agent-b12"))
        self.repo = AgentInstanceRuntimeHealthRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    def test_controller_persists_only_owned_health_projection(self):
        applied = self.repo.apply_inventory("agent-b12", [{
            "instance_id": "instance-b12", "desired_state": "running", "observed_state": "running",
            "reconcile_status": "healthy", "health": "healthy", "operation_status": "idle",
        }, {"instance_id": "missing", "health": "healthy"}])
        self.assertEqual(applied, [{"instance_id": "instance-b12", "health": "healthy", "operation_status": "idle"}])
        rows = self.repo.list_for_agent("agent-b12")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["health"], "healthy")


if __name__ == "__main__":
    unittest.main()
