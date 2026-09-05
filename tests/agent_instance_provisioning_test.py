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
import provisioning_executor
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from provisioning_contract import ProvisioningContractError, validate_provisioning_request
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class ProvisioningContractTest(unittest.TestCase):
    def request(self):
        return {
            "provisioning_id": "instance-provision-1",
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "environment_id": "dayz.stable",
            "selector": "stable",
            "desired_state": "running",
            "instance": {
                "instance_id": "instance-one",
                "agent_id": "agent-one",
                "game_id": "dayz",
                "environment_id": "dayz.stable",
                "runtime_id": "runtime-one",
            },
            "content": {"action": "install", "selection": {"game": "dayz", "provider": "steam"}},
            "ports": {"game": {"port": 24000, "protocol": "udp"}},
            "configuration": {},
        }

    def test_contract_enforces_agent_ownership_and_reserved_ports(self):
        validated = validate_provisioning_request(self.request(), expected_agent_id="agent-one")
        self.assertEqual(validated["ports"]["game"]["port"], 24000)
        foreign = self.request(); foreign["agent_id"] = "agent-two"
        with self.assertRaises(ProvisioningContractError):
            validate_provisioning_request(foreign, expected_agent_id="agent-one")

    def test_contract_rejects_remote_shell_or_runtime_authority(self):
        for forbidden in ("shell", "command", "argv", "unit", "service"):
            request = self.request(); request["configuration"] = {forbidden: "unsafe"}
            with self.assertRaises(ProvisioningContractError):
                validate_provisioning_request(request, expected_agent_id="agent-one")


class ProvisioningExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        instance_runtime.STATE_DIR = self.root / "state"
        self.config = {"agent_id": "agent-one"}
        self.request = ProvisioningContractTest().request()
        self.result_path = self.root / "result.json"
        self.old_content = provisioning_executor.execute_game_data
        self.old_build = provisioning_executor.game_runtime.build_runtime_spec
        self.old_materialize = provisioning_executor.privileged_materialization.materialize
        self.old_reconcile = provisioning_executor.runtime_materialization.reconcile
        self.old_remove = provisioning_executor.privileged_materialization.remove

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        provisioning_executor.execute_game_data = self.old_content
        provisioning_executor.game_runtime.build_runtime_spec = self.old_build
        provisioning_executor.privileged_materialization.materialize = self.old_materialize
        provisioning_executor.runtime_materialization.reconcile = self.old_reconcile
        provisioning_executor.privileged_materialization.remove = self.old_remove
        self.temp.cleanup()

    def _wire_success(self):
        install = self.root / "game-data" / "dayz" / "serverfiles"; install.mkdir(parents=True)
        provisioning_executor.execute_game_data = lambda command: {
            "provider": "steam", "game": "dayz", "version": "stable", "target_path": str(install)
        }
        provisioning_executor.game_runtime.build_runtime_spec = lambda config, instance, context: {
            "instance_id": instance["instance_id"], "agent_id": instance["agent_id"], "runtime_id": instance["runtime_id"],
            "adapter": "systemd", "profile": "dayz", "profile_version": 1,
        }
        provisioning_executor.privileged_materialization.materialize = lambda config, spec: {"operation": {"changed": True}}
        provisioning_executor.runtime_materialization.reconcile = lambda config, instance_id: {"observed_state": "running"}

    def test_pipeline_runs_content_profile_materialization_and_reconcile(self):
        self._wire_success()
        result = provisioning_executor.execute(self.config, self.request, self.result_path)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["progress"], 100)
        self.assertEqual(result["observed_state"], "running")
        self.assertEqual(result["runtime"]["profile"], "dayz")
        self.assertEqual(result["content"]["provider"], "steam")
        self.assertTrue((Path(result["workspace"]["root"])).is_dir())

    def test_failure_after_materialization_compensates_runtime_but_preserves_content_and_ports(self):
        self._wire_success()
        removed = []
        provisioning_executor.runtime_materialization.reconcile = lambda config, instance_id: (_ for _ in ()).throw(RuntimeError("start failed"))
        provisioning_executor.privileged_materialization.remove = lambda config, instance_id: removed.append(instance_id) or {"operation": {"changed": True}}
        result = provisioning_executor.execute(self.config, self.request, self.result_path)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(removed, ["instance-one"])
        self.assertIn("runtime_removed", result["compensation"])
        self.assertIn("content_preserved_for_retry", result["compensation"])
        self.assertIn("port_reservations_preserved", result["compensation"])


class ControllerProvisioningQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="b10-controller")
        issued = AgentPairingRepository(self.backend).issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        status, enrolled = dispatch_enroll({
            "pairing_token": issued.token, "agent_id": "agent-b10", "node_id": "node-b10", "name": "B10 Agent",
            "fingerprint": "sha256:b10-agent", "hostname": "b10-agent", "os": "linux", "architecture": "x86_64",
        }, backend=self.backend)
        self.assertEqual(status, 201)
        self.controller_id = enrolled["controller_id"]
        self.customer_id = 1
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:b10-agent",
        }
        status, _ = dispatch_heartbeat({"agent_id": "agent-b10"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        with self.backend.transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", (self.customer_id, self.controller_id, "Customer", "active"))
            cur.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-b10", "node-b10", "dayz", "dayz.stable", "Instance B10", "offline", self.controller_id, "agent-b10", self.customer_id),
            )
            cur.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                ("instance-b10", "node-b10", "game", "udp", 24000),
            )
            cur.close()
        self.jobs = AgentInstanceProvisioningRepository(self.backend); self.jobs.initialize()

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    def test_enqueue_binds_existing_port_reservations_and_is_idempotent_while_active(self):
        first = self.jobs.enqueue(
            agent_id="agent-b10", instance_id="instance-b10", environment_id="dayz.stable", selector="stable",
            selection={"game": "dayz", "provider": "steam", "install": {"package_id": "223350"}}, desired_state="running",
        )
        second = self.jobs.enqueue(
            agent_id="agent-b10", instance_id="instance-b10", environment_id="dayz.stable", selector="stable",
            selection={"game": "dayz", "provider": "steam", "install": {"package_id": "223350"}}, desired_state="running",
        )
        self.assertEqual(first["provisioning_id"], second["provisioning_id"])
        self.assertEqual(first["request"]["ports"]["game"]["port"], 24000)

    def test_authenticated_heartbeat_delivers_progress_and_completion(self):
        created = self.jobs.enqueue(
            agent_id="agent-b10", instance_id="instance-b10", environment_id="dayz.stable", selector="stable",
            selection={"game": "dayz", "provider": "steam", "install": {"package_id": "223350"}}, desired_state="running",
        )
        status, delivered = dispatch_heartbeat({"agent_id": "agent-b10"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(delivered["provisioning_command"]["provisioning_id"], created["provisioning_id"])
        self.assertEqual(delivered["game_data_state"]["status"], "deferred")
        status, running = dispatch_heartbeat({
            "agent_id": "agent-b10",
            "provisioning_result": {
                "provisioning_id": created["provisioning_id"], "instance_id": "instance-b10",
                "status": "running", "current_step": "install_content", "progress": 42,
            },
        }, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(running["provisioning_state"]["progress"], 42)
        status, completed = dispatch_heartbeat({
            "agent_id": "agent-b10",
            "provisioning_result": {
                "provisioning_id": created["provisioning_id"], "instance_id": "instance-b10",
                "status": "completed", "current_step": "completed", "progress": 100,
                "desired_state": "running", "observed_state": "running",
            },
        }, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(completed["provisioning_state"]["status"], "completed")
        self.assertNotIn("provisioning_command", completed)

    def test_wrong_agent_and_missing_ports_are_rejected(self):
        with self.assertRaises(ValueError):
            self.jobs.enqueue(
                agent_id="missing-agent", instance_id="instance-b10", environment_id="dayz.stable", selector="stable",
                selection={"game": "dayz"},
            )
        with self.backend.transaction() as conn:
            conn.execute("DELETE FROM instance_ports WHERE instance_id=?", ("instance-b10",))
        with self.assertRaises(ValueError):
            self.jobs.enqueue(
                agent_id="agent-b10", instance_id="instance-b10", environment_id="dayz.stable", selector="stable",
                selection={"game": "dayz"},
            )


    def test_latest_for_instance_returns_most_recent(self):
        first = self.jobs.enqueue(
            agent_id="agent-b10",
            instance_id="instance-b10",
            environment_id="dayz.stable",
            selector="stable",
            selection={"game": "dayz"},
            desired_state="running",
        )

        self.jobs.apply_result(
            "agent-b10",
            {
                "provisioning_id": first["provisioning_id"],
                "instance_id": "instance-b10",
                "status": "completed",
                "current_step": "completed",
                "progress": 100,
                "observed_state": "stopped",
            },
        )

        second = self.jobs.enqueue(
            agent_id="agent-b10",
            instance_id="instance-b10",
            environment_id="dayz.stable",
            selector="stable",
            selection={"game": "dayz"},
            desired_state="running",
        )

        latest = self.jobs.latest_for_instance("instance-b10")

        self.assertIsNotNone(latest)
        self.assertEqual(
            second["provisioning_id"],
            latest["provisioning_id"],
        )
        self.assertNotEqual(
            first["provisioning_id"],
            latest["provisioning_id"],
        )


if __name__ == "__main__":
    unittest.main()
