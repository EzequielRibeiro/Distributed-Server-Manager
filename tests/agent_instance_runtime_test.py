#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentLocalInstanceRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.original = (instance_runtime.STATE_DIR, instance_runtime.INSTANCE_DIR, instance_runtime.RESULT_DIR, instance_runtime.HISTORY_DIR)
        instance_runtime.STATE_DIR = self.state
        instance_runtime.INSTANCE_DIR = self.state / "instances"
        instance_runtime.RESULT_DIR = self.state / "instance-results"
        instance_runtime.HISTORY_DIR = self.state / "instance-command-history"
        self.config = {"agent_id": "agent-one"}

    def tearDown(self):
        instance_runtime.STATE_DIR, instance_runtime.INSTANCE_DIR, instance_runtime.RESULT_DIR, instance_runtime.HISTORY_DIR = self.original
        self.temp.cleanup()

    def test_status_doctor_and_inventory_are_agent_owned(self):
        target = self.state / "serverfiles"; target.mkdir()
        instance_runtime.register_instance({
            "instance_id": "instance-one", "agent_id": "agent-one", "game_id": "generic-game",
            "environment_id": "generic.stable", "runtime_id": "runtime-one", "adapter": "native",
            "path": str(target), "observed_state": "stopped",
        })
        view = instance_runtime.status(self.config, "instance-one")
        self.assertTrue(view["path_exists"])
        self.assertEqual(view["scope"], "instance-local")
        doctor = instance_runtime.doctor(self.config, "instance-one")
        self.assertEqual(doctor["status"], "healthy")
        self.assertEqual(len(instance_runtime.inventory(self.config)), 1)

    def test_ownership_and_action_allowlist_are_enforced(self):
        instance_runtime.register_instance({"instance_id": "foreign", "agent_id": "agent-two"})
        with self.assertRaises(PermissionError):
            instance_runtime.status(self.config, "foreign")
        result = instance_runtime.handle_command(self.config, {"command_id": "cmd-shell", "instance_id": "foreign", "action": "shell"})
        self.assertEqual(result["status"], "failed")
        self.assertIn("unsupported instance action", result["error"])

    def test_command_is_idempotent_and_history_survives_ack(self):
        instance_runtime.register_instance({"instance_id": "instance-one", "agent_id": "agent-one"})
        command = {"command_id": "cmd-one", "instance_id": "instance-one", "action": "status"}
        first = instance_runtime.handle_command(self.config, command)
        second = instance_runtime.handle_command(self.config, command)
        self.assertEqual(first, second)
        self.assertIsNotNone(instance_runtime.read_result())
        instance_runtime.clear_result("cmd-one")
        self.assertIsNone(instance_runtime.read_result())
        self.assertTrue((instance_runtime.HISTORY_DIR / "cmd-one.json").is_file())


class ControllerInstanceRuntimeQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="instance-controller")
        issued = AgentPairingRepository(self.backend).issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        status, enrolled = dispatch_enroll({
            "pairing_token": issued.token, "agent_id": "agent-instance", "node_id": "node-instance", "name": "Instance Agent",
            "fingerprint": "sha256:instance-agent", "hostname": "instance-agent", "os": "linux", "architecture": "x86_64",
        }, backend=self.backend)
        self.assertEqual(status, 201)
        self.controller_id = enrolled["controller_id"]
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:instance-agent",
        }
        status, _ = dispatch_heartbeat({"agent_id": "agent-instance"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        with self.backend.transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", ("customer-instance", self.controller_id, "Customer", "active"))
            cur.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                ("instance-one", "node-instance", "generic-game", "Instance One", "offline", self.controller_id, "agent-instance", "customer-instance"),
            )
            cur.close()
        self.commands = AgentInstanceRuntimeRepository(self.backend); self.commands.initialize()

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    def test_authenticated_heartbeat_delivers_and_acknowledges_observation(self):
        created = self.commands.enqueue(agent_id="agent-instance", instance_id="instance-one", action="doctor")
        status, delivered = dispatch_heartbeat({"agent_id": "agent-instance"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(delivered["instance_command"]["command_id"], created["command_id"])
        self.assertEqual(delivered["instance_state"]["status"], "delivered")
        status, completed = dispatch_heartbeat({
            "agent_id": "agent-instance",
            "instance_result": {"command_id": created["command_id"], "instance_id": "instance-one", "action": "doctor", "status": "completed", "result": {"status": "healthy"}},
        }, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(completed["instance_state"]["status"], "completed")
        self.assertNotIn("instance_command", completed)

    def test_controller_rejects_wrong_agent_ownership_and_unsafe_action(self):
        with self.assertRaises(ValueError):
            self.commands.enqueue(agent_id="agent-instance", instance_id="instance-one", action="shell")
        with self.assertRaises(ValueError):
            self.commands.enqueue(agent_id="missing-agent", instance_id="instance-one", action="status")


if __name__ == "__main__":
    unittest.main()
