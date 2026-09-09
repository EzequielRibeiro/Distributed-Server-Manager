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
from agent_instance_provisioning_api import (
    instance_provisioning_diagnostics,
    instance_provisioning_status,
)
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from alert_repository import AlertRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentFailureCaptureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        instance_runtime.STATE_DIR = self.root / "state"
        self.old_content = provisioning_executor.execute_game_data
        self.request = {
            "provisioning_id": "instance-provision-diagnostics-agent",
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "environment_id": "dayz.stable",
            "selector": "stable",
            "desired_state": "stopped",
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

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        provisioning_executor.execute_game_data = self.old_content
        self.temp.cleanup()

    def test_agent_failure_is_below_100_and_sanitized_before_result_persistence(self):
        def fail(_command):
            raise RuntimeError(
                "install failed password=hunter2 Authorization: Bearer super-secret +login steamuser steampass "
                "at C:\\Users\\Ezequiel\\Capivara\\server.exe"
            )

        provisioning_executor.execute_game_data = fail
        result = provisioning_executor.execute(
            {"agent_id": "agent-one"},
            self.request,
            self.root / "result.json",
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["progress"], 99)
        self.assertEqual(result["current_step"], "install_content")
        self.assertEqual(result["exception_type"], "RuntimeError")
        self.assertEqual(result["correlation_id"], self.request["provisioning_id"])
        self.assertTrue(result["failed_at"].endswith("Z"))
        self.assertIn("Traceback", result["traceback"])
        rendered = str(result)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("steampass", rendered)
        self.assertNotIn("Ezequiel", rendered)
        self.assertIn("<USER_HOME>/", rendered)
        self.assertIn("[REDACTED]", rendered)


class ControllerFailureDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="diagnostics-controller"
        )
        issued = AgentPairingRepository(self.backend).issue_token(
            controller_id=str(identity["controller_id"]), ttl_seconds=300
        )
        status, enrolled = dispatch_enroll(
            {
                "pairing_token": issued.token,
                "agent_id": "agent-diagnostics",
                "node_id": "node-diagnostics",
                "name": "Diagnostics Agent",
                "fingerprint": "sha256:diagnostics-agent",
                "hostname": "diagnostics-agent",
                "os": "linux",
                "architecture": "x86_64",
            },
            backend=self.backend,
        )
        self.assertEqual(status, 201)
        self.controller_id = enrolled["controller_id"]
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:diagnostics-agent",
        }
        status, _ = dispatch_heartbeat(
            {"agent_id": "agent-diagnostics"}, headers=self.headers, backend=self.backend
        )
        self.assertEqual(status, 200)
        with self.backend.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                (901, self.controller_id, "AURORA", "active"),
            )
            cur.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "instance-diagnostics",
                    "node-diagnostics",
                    "palworld",
                    "palworld.stable",
                    "Palworld Diagnostics",
                    "offline",
                    self.controller_id,
                    "agent-diagnostics",
                    901,
                ),
            )
            cur.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                ("instance-diagnostics", "node-diagnostics", "game", "udp", 8211),
            )
            cur.close()
        self.jobs = AgentInstanceProvisioningRepository(self.backend)
        self.jobs.initialize()
        self.created = self.jobs.enqueue(
            agent_id="agent-diagnostics",
            instance_id="instance-diagnostics",
            environment_id="palworld.stable",
            selector="stable",
            selection={"game": "palworld", "provider": "steam", "install": {"package_id": "2394010"}},
            desired_state="running",
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _failure(self):
        return {
            "provisioning_id": self.created["provisioning_id"],
            "instance_id": "instance-diagnostics",
            "status": "failed",
            "current_step": "install_content",
            "progress": 100,
            "error": "Steam failed password=topsecret Authorization: Bearer abc123",
            "exception_type": "RuntimeError",
            "source": "agent.provisioning_executor",
            "failed_at": "2026-09-09T15:30:00.000Z",
            "correlation_id": self.created["provisioning_id"],
            "traceback": (
                "Traceback (most recent call last):\n"
                "  File \"/opt/dsm/agents/linux/runtime/provisioning_executor.py\", line 1\n"
                "  File \"C:\\Users\\Ezequiel\\Capivara\\runtime.py\", line 2\n"
                "RuntimeError: token=trace-secret password=trace-pass"
            ),
        }

    def test_controller_persists_safe_diagnostics_and_admin_gets_traceback(self):
        state = self.jobs.apply_result("agent-diagnostics", self._failure())
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["progress"], 99)
        self.assertNotIn("traceback", state["result"])
        self.assertEqual(state["result"]["exception_type"], "RuntimeError")

        controller_view = instance_provisioning_status(
            self.created["provisioning_id"],
            user={"role": "controller", "username": "regional-controller"},
            backend=self.backend,
        )
        self.assertNotIn("traceback", controller_view["result"])
        with self.assertRaises(PermissionError):
            instance_provisioning_diagnostics(
                self.created["provisioning_id"],
                user={"role": "controller", "username": "regional-controller"},
                backend=self.backend,
            )

        admin_view = instance_provisioning_diagnostics(
            self.created["provisioning_id"],
            user={"role": "admin", "username": "root-admin"},
            backend=self.backend,
        )
        self.assertEqual(admin_view["stage"], "install_content")
        self.assertEqual(admin_view["agent_id"], "agent-diagnostics")
        self.assertEqual(admin_view["node_id"], "node-diagnostics")
        self.assertEqual(admin_view["instance_id"], "instance-diagnostics")
        self.assertEqual(admin_view["game"], "palworld")
        self.assertEqual(admin_view["customer"], "AURORA")
        self.assertEqual(admin_view["exception_type"], "RuntimeError")
        self.assertEqual(admin_view["correlation_id"], self.created["provisioning_id"])
        self.assertIn("<DSM_ROOT>/", admin_view["traceback"])
        self.assertIn("<USER_HOME>/", admin_view["traceback"])
        rendered = str(admin_view)
        self.assertNotIn("topsecret", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("trace-secret", rendered)
        self.assertNotIn("trace-pass", rendered)
        self.assertNotIn("Ezequiel", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_failure_opens_one_rich_critical_alert_and_repeated_result_is_deduplicated(self):
        failure = self._failure()
        self.jobs.apply_result("agent-diagnostics", failure)
        self.jobs.apply_result("agent-diagnostics", failure)

        alert_id = f"instance-provisioning-failed:{self.created['provisioning_id']}"
        alerts = AlertRepository(self.backend)
        alert = alerts.get_alert(alert_id)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["level"], "CRITICAL")
        self.assertEqual(alert["instance_id"], "instance-diagnostics")
        self.assertEqual(alert["agent_id"], "agent-diagnostics")
        self.assertEqual(alert["node_id"], "node-diagnostics")
        self.assertIn("palworld", alert["message"])
        self.assertIn("AURORA", alert["message"])
        self.assertIn("etapa=install_content", alert["message"])
        self.assertIn(self.created["provisioning_id"], alert["message"])
        self.assertEqual(len(alerts.alert_history(alert_id)), 1)


if __name__ == "__main__":
    unittest.main()
