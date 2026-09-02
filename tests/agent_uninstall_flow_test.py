#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

import dashboard.agent_heartbeat_api as heartbeat_api
import uninstall_client


def _load_executor():
    path = ROOT / "agents" / "linux" / "privileged" / "uninstall_agent.py"
    spec = importlib.util.spec_from_file_location("capivara_test_uninstall_executor", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


executor = _load_executor()


class HeartbeatUninstallExchangeTest(unittest.TestCase):
    def test_exchange_applies_result_before_requesting_next_command(self):
        calls = []

        class FakeRepository:
            def __init__(self, backend):
                self.backend = backend
                calls.append(("init", backend))

            def initialize(self):
                calls.append(("initialize",))

            def apply_result(self, agent_id, result):
                calls.append(("apply_result", agent_id, result))
                return {"status": "accepted", "request_id": result["request_id"]}

            def command_for_agent(self, agent_id):
                calls.append(("command_for_agent", agent_id))
                return {
                    "kind": "AgentUninstallCommand",
                    "schema_version": 1,
                    "action": "uninstall-agent",
                    "phase": "commit",
                    "mode": "purge",
                    "request_id": "uninstall-test",
                }

        payload = {
            "uninstall_result": {
                "request_id": "uninstall-test",
                "status": "accepted",
                "accepted_at": "2026-09-02T00:00:00Z",
            }
        }
        with mock.patch.object(heartbeat_api, "AgentUninstallRepository", FakeRepository):
            command, state = heartbeat_api._uninstall_exchange(
                "agent-test", payload, backend="backend"
            )

        self.assertEqual("accepted", state["status"])
        self.assertEqual("commit", command["phase"])
        self.assertEqual(
            ["init", "initialize", "apply_result", "command_for_agent"],
            [item[0] for item in calls],
        )

    def test_exchange_without_result_still_delivers_command(self):
        class FakeRepository:
            def __init__(self, backend):
                pass

            def initialize(self):
                pass

            def apply_result(self, agent_id, result):
                raise AssertionError("apply_result must not be called")

            def command_for_agent(self, agent_id):
                return {"phase": "prepare", "request_id": "uninstall-test"}

        with mock.patch.object(heartbeat_api, "AgentUninstallRepository", FakeRepository):
            command, state = heartbeat_api._uninstall_exchange(
                "agent-test", {}, backend=object()
            )
        self.assertIsNone(state)
        self.assertEqual("prepare", command["phase"])


class LinuxUninstallClientTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patchers = [
            mock.patch.object(uninstall_client, "STATE_DIR", self.root),
            mock.patch.object(uninstall_client, "UNINSTALL_DIR", self.root / "uninstall"),
            mock.patch.object(uninstall_client, "RESULT_PATH", self.root / "uninstall" / "result.json"),
            mock.patch.object(uninstall_client, "REQUEST_PATH", self.root / "uninstall" / "request.json"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    @staticmethod
    def command(phase="prepare", request_id="uninstall-test", mode="purge"):
        return {
            "kind": "AgentUninstallCommand",
            "schema_version": 1,
            "action": "uninstall-agent",
            "phase": phase,
            "mode": mode,
            "request_id": request_id,
        }

    @staticmethod
    def config():
        return {
            "agent_id": "agent-test",
            "controller_url": "https://controller.example:9443",
            "credential_id": "credential-test",
            "credential_secret": "secret-test",
            "fingerprint": "sha256:test",
            "instance_storage_root": "/var/lib/capivara-instances",
        }

    def test_prepare_writes_accepted_result_and_is_idempotent(self):
        first = uninstall_client.handle_command(self.config(), self.command())
        second = uninstall_client.handle_command(self.config(), self.command())
        self.assertEqual("accepted", first["status"])
        self.assertEqual(first, second)
        stored = json.loads(uninstall_client.RESULT_PATH.read_text())
        self.assertEqual("uninstall-test", stored["request_id"])
        self.assertEqual("accepted", stored["status"])

    def test_invalid_command_is_rejected(self):
        command = self.command()
        command["action"] = "shell"
        with self.assertRaises(ValueError):
            uninstall_client.handle_command(self.config(), command)

    def test_commit_requires_permanent_credentials(self):
        config = self.config()
        del config["credential_secret"]
        with self.assertRaises(RuntimeError):
            uninstall_client.handle_command(config, self.command("commit"))
        self.assertFalse(uninstall_client.REQUEST_PATH.exists())

    def test_commit_stages_typed_request_and_is_idempotent(self):
        command = self.command("commit")
        first = uninstall_client.handle_command(self.config(), command)
        second = uninstall_client.handle_command(self.config(), command)
        self.assertEqual("commit-staged", first["status"])
        self.assertEqual("commit-staged", second["status"])
        staged = json.loads(uninstall_client.REQUEST_PATH.read_text())
        self.assertEqual("CapivaraLinuxUninstallRequest", staged["kind"])
        self.assertEqual(1, staged["schema_version"])
        self.assertEqual("agent-test", staged["agent_id"])
        self.assertEqual("purge", staged["mode"])

    def test_conflicting_commit_is_rejected(self):
        uninstall_client.handle_command(self.config(), self.command("commit"))
        with self.assertRaises(RuntimeError):
            uninstall_client.handle_command(
                self.config(), self.command("commit", request_id="uninstall-other")
            )


class LinuxPrivilegedUninstallExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.install = self.root / "opt" / "capivara-agent"
        self.config = self.root / "etc" / "capivara-agent"
        self.state = self.root / "var" / "lib" / "capivara-agent"
        self.data = self.root / "var" / "lib" / "capivara-instances"
        self.install.mkdir(parents=True)
        (self.install / "runtime").mkdir()
        (self.install / "runtime" / "agent.py").write_text("runtime\n")
        (self.install / "privileged").mkdir()
        (self.install / "privileged" / "uninstall_agent.py").write_text("executor\n")
        (self.install / "privileged" / "other.py").write_text("other\n")
        self.config.mkdir(parents=True)
        self.state.mkdir(parents=True)
        self.data.mkdir(parents=True)
        (self.data / "world.dat").write_text("managed-data\n")
        self.patchers = [
            mock.patch.object(executor, "INSTALL_ROOT", self.install),
            mock.patch.object(executor, "CONFIG_DIR", self.config),
            mock.patch.object(executor, "STATE_DIR", self.state),
            mock.patch.object(executor, "_ALLOWED_DEFAULT_DATA_ROOTS", {self.data.resolve()}),
            mock.patch.object(executor, "_stop_runtime"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def request(self, mode):
        return {
            "request_id": "uninstall-test",
            "mode": mode,
            "agent_id": "agent-test",
            "controller_url": "https://controller.example:9443",
            "credential_id": "credential-test",
            "credential_secret": "secret-test",
            "fingerprint": "sha256:test",
            "instance_storage_root": str(self.data),
        }

    def test_preserve_data_removes_runtime_but_keeps_managed_data(self):
        result = executor._remove_payload(self.request("preserve-data"))
        self.assertTrue(result["service_stopped"])
        self.assertTrue(result["runtime_removed"])
        self.assertFalse(result["data_removed"])
        self.assertTrue(self.data.exists())
        self.assertFalse((self.install / "runtime").exists())
        self.assertTrue((self.install / "privileged" / "uninstall_agent.py").exists())

    def test_purge_removes_allowlisted_managed_data(self):
        result = executor._remove_payload(self.request("purge"))
        self.assertTrue(result["data_removed"])
        self.assertFalse(self.data.exists())

    def test_purge_preserves_non_allowlisted_path(self):
        other = self.root / "customer-data"
        other.mkdir()
        request = self.request("purge")
        request["instance_storage_root"] = str(other)
        result = executor._remove_payload(request)
        self.assertTrue(other.exists())
        self.assertFalse(result["data_removed"])
        self.assertIn("preserved", result["data_note"])

    def test_main_reports_committed_before_removal_and_completed_before_finalizer(self):
        request = self.request("preserve-data")
        events = []

        def report(_request, status, **kwargs):
            events.append(("report", status))
            return {}

        def remove(_request):
            events.append(("remove", None))
            return {"service_stopped": True, "runtime_removed": True, "data_removed": False}

        def finalizer():
            events.append(("finalizer", None))

        with mock.patch.object(executor.os, "geteuid", return_value=0), \
             mock.patch.object(executor, "_load_request", return_value=request), \
             mock.patch.object(executor, "_report", side_effect=report), \
             mock.patch.object(executor, "_remove_payload", side_effect=remove), \
             mock.patch.object(executor, "_schedule_finalizer", side_effect=finalizer):
            rc = executor.main()

        self.assertEqual(0, rc)
        self.assertEqual(
            [
                ("report", "committed"),
                ("remove", None),
                ("report", "completed"),
                ("finalizer", None),
            ],
            events,
        )


if __name__ == "__main__":
    unittest.main()
