#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT,
    ROOT / "database",
    ROOT / "dashboard",
    ROOT / "agents" / "linux" / "runtime",
    ROOT / "agents" / "linux" / "provisioner",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_provisioner
import instance_runtime
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class PrivilegedProvisionerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.state = base / "state"
        self.data = base / "instance-data"
        self.game_data = base / "game-data" / "generic"
        self.systemd = base / "systemd"
        self.state.mkdir()
        self.systemd.mkdir()
        self.game_data.mkdir(parents=True)
        self.original = (
            instance_provisioner.STATE_DIR,
            instance_provisioner.ROOT,
            instance_provisioner.REQUEST_DIR,
            instance_provisioner.RESULT_DIR,
            instance_provisioner.HISTORY_DIR,
            instance_provisioner.INSTANCE_DATA_ROOT,
            instance_provisioner.SYSTEMD_DIR,
        )
        instance_provisioner.STATE_DIR = self.state
        instance_provisioner.ROOT = self.state / "instance-provisioning"
        instance_provisioner.REQUEST_DIR = instance_provisioner.ROOT / "requests"
        instance_provisioner.RESULT_DIR = instance_provisioner.ROOT / "results"
        instance_provisioner.HISTORY_DIR = instance_provisioner.ROOT / "history"
        instance_provisioner.INSTANCE_DATA_ROOT = self.data
        instance_provisioner.SYSTEMD_DIR = self.systemd
        self.owner = patch.object(instance_provisioner, "_state_owner", return_value=(os.getuid(), os.getgid()))
        self.owner.start()
        self.game_state = patch.object(
            instance_provisioner,
            "get_game_data",
            return_value={"game": "generic", "installed": True, "target_path": str(self.game_data)},
        )
        self.game_state.start()

    def tearDown(self):
        self.game_state.stop()
        self.owner.stop()
        (
            instance_provisioner.STATE_DIR,
            instance_provisioner.ROOT,
            instance_provisioner.REQUEST_DIR,
            instance_provisioner.RESULT_DIR,
            instance_provisioner.HISTORY_DIR,
            instance_provisioner.INSTANCE_DATA_ROOT,
            instance_provisioner.SYSTEMD_DIR,
        ) = self.original
        self.temp.cleanup()

    def runtime(self):
        return {
            "runtime_id": "generic.stable",
            "environment_id": "generic.stable",
            "game_id": "generic",
            "adapter": "systemd",
            "launch": {
                "engine": "native",
                "executable": "server-bin",
                "arguments": ["--port=24000", "hello world"],
            },
        }

    def request(self, action="provision"):
        return {
            "job_id": "job-one",
            "agent_id": "agent-one",
            "instance_id": "instance-one",
            "action": action,
            "runtime": self.runtime(),
        }

    def _install_fake_binary(self):
        binary = self.game_data / "server-bin"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def test_unit_is_derived_and_controller_cannot_supply_execstart(self):
        binary = self._install_fake_binary()
        working = self.data / "instance-one" / "serverfiles"
        working.mkdir(parents=True)
        runtime = instance_provisioner._runtime_contract(self.request())
        content = instance_provisioner.render_unit("instance-one", binary, working, runtime["arguments"])
        self.assertIn("capivara", content.lower())
        self.assertIn(str(binary), content)
        self.assertNotIn("/bin/sh -c", content)
        unsafe = self.request()
        unsafe["runtime"]["launch"]["executable"] = "../../bin/sh"
        with self.assertRaises(ValueError):
            instance_provisioner._runtime_contract(unsafe)
        request = self.request()
        request["unit"] = "sshd.service"
        self.assertEqual(instance_provisioner.unit_for_instance(request["instance_id"]), "capivara-instance-instance-one.service")

    def test_provision_and_reconcile_are_deterministic(self):
        self._install_fake_binary()
        with patch.object(instance_provisioner, "_run", return_value=(0, "")):
            first = instance_provisioner._materialize(self.request())
            second = instance_provisioner._materialize(self.request("reconcile"))
        self.assertEqual(first["status"], "completed")
        self.assertTrue(first["unit_changed"])
        self.assertFalse(second["unit_changed"])
        self.assertEqual(first["instance_record"]["provisioning_status"], "ready")
        self.assertTrue((self.systemd / "capivara-instance-instance-one.service").is_file())

    def test_unit_is_rolled_back_when_daemon_reload_fails(self):
        self._install_fake_binary()
        unit = self.systemd / "capivara-instance-instance-one.service"
        unit.write_text("old unit\n", encoding="utf-8")
        calls = {"count": 0}

        def runner(command, timeout=30, check=True):
            if command[:2] == ["systemd-analyze", "verify"]:
                return 0, ""
            if command[:2] == ["systemctl", "daemon-reload"]:
                calls["count"] += 1
                if calls["count"] == 1:
                    if check:
                        raise RuntimeError("reload failed")
                    return 1, "reload failed"
                return 0, ""
            return 0, ""

        with patch.object(instance_provisioner, "_run", side_effect=runner):
            with self.assertRaises(RuntimeError):
                instance_provisioner._materialize(self.request())
        self.assertEqual(unit.read_text(encoding="utf-8"), "old unit\n")

    def test_remove_preserves_instance_data(self):
        self._install_fake_binary()
        serverfiles = self.data / "instance-one" / "serverfiles"
        serverfiles.mkdir(parents=True)
        marker = serverfiles / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        unit = self.systemd / "capivara-instance-instance-one.service"
        unit.write_text("unit\n", encoding="utf-8")
        request = self.request("remove")
        request.pop("runtime")
        with patch.object(instance_provisioner, "_run", return_value=(0, "")):
            result = instance_provisioner._materialize(request)
        self.assertTrue(result["data_preserved"])
        self.assertFalse(unit.exists())
        self.assertTrue(marker.exists())


class ControllerProvisioningQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        identity = installation_profile_identity(RegistryRepository(self.backend), profile="controller", hostname="provision-controller")
        issued = AgentPairingRepository(self.backend).issue_token(controller_id=str(identity["controller_id"]), ttl_seconds=300)
        status, enrolled = dispatch_enroll({
            "pairing_token": issued.token,
            "agent_id": "agent-provision",
            "node_id": "node-provision",
            "name": "Provision Agent",
            "fingerprint": "sha256:provision-agent",
            "hostname": "provision-agent",
            "os": "linux",
            "architecture": "x86_64",
        }, backend=self.backend)
        self.assertEqual(status, 201)
        self.controller_id = enrolled["controller_id"]
        self.headers = {
            "X-Capivara-Agent-Credential": enrolled["credential_id"],
            "X-Capivara-Agent-Secret": enrolled["credential_secret"],
            "X-Capivara-Agent-Fingerprint": "sha256:provision-agent",
        }
        status, _ = dispatch_heartbeat({"agent_id": "agent-provision"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        with self.backend.transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)", ("customer-provision", self.controller_id, "Customer", "active"))
            cur.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",
                ("instance-one", "node-provision", "generic", "Instance One", "offline", self.controller_id, "agent-provision", "customer-provision"),
            )
            cur.close()
        self.jobs = AgentInstanceProvisioningRepository(self.backend)
        self.jobs.initialize()
        self.runtime = {
            "runtime_id": "generic.stable",
            "environment_id": "generic.stable",
            "game_id": "generic",
            "adapter": "systemd",
            "launch": {"engine": "native", "executable": "server-bin", "arguments": []},
        }

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_heartbeat_delivers_and_acknowledges_provisioning(self):
        created = self.jobs.enqueue(
            agent_id="agent-provision", instance_id="instance-one", action="provision", runtime=self.runtime
        )
        status, delivered = dispatch_heartbeat({"agent_id": "agent-provision"}, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        command = delivered["instance_provisioning_command"]
        self.assertEqual(command["job_id"], created["job_id"])
        self.assertEqual(command["runtime"]["launch"]["executable"], "server-bin")
        status, completed = dispatch_heartbeat({
            "agent_id": "agent-provision",
            "instance_provisioning_result": {
                "job_id": created["job_id"],
                "agent_id": "agent-provision",
                "instance_id": "instance-one",
                "action": "provision",
                "status": "completed",
                "unit": "capivara-instance-instance-one.service",
            },
        }, headers=self.headers, backend=self.backend)
        self.assertEqual(status, 200)
        self.assertEqual(completed["instance_provisioning_state"]["status"], "completed")

    def test_queue_enforces_ownership_game_and_single_pending_job(self):
        with self.assertRaises(ValueError):
            self.jobs.enqueue(agent_id="agent-provision", instance_id="instance-one", action="provision", runtime={**self.runtime, "game_id": "other"})
        first = self.jobs.enqueue(agent_id="agent-provision", instance_id="instance-one", action="provision", runtime=self.runtime)
        self.assertEqual(first["status"], "queued")
        with self.assertRaises(ValueError):
            self.jobs.enqueue(agent_id="agent-provision", instance_id="instance-one", action="reconcile", runtime=self.runtime)

    def test_result_metadata_mismatch_is_rejected(self):
        created = self.jobs.enqueue(agent_id="agent-provision", instance_id="instance-one", action="remove")
        with self.assertRaises(ValueError):
            self.jobs.apply_result("agent-provision", {
                "job_id": created["job_id"], "instance_id": "other", "action": "remove", "status": "completed"
            })
        with self.assertRaises(ValueError):
            self.jobs.apply_result("agent-provision", {
                "job_id": created["job_id"], "instance_id": "instance-one", "action": "provision", "status": "completed"
            })
        self.assertEqual(self.jobs.snapshot(created["job_id"])["status"], "queued")


if __name__ == "__main__":
    unittest.main()
