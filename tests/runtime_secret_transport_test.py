#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard", ROOT / "agents/linux/runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from configuration_client import apply_configuration
from runtime_secret_repository import RuntimeSecretOutbox


class DummyBackend:
    name = "sqlite"


class RuntimeSecretTransportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_outbox = os.environ.get("DSM_RUNTIME_SECRET_OUTBOX")
        self.old_agent_secret = os.environ.get("CAPIVARA_RUNTIME_SECRET_ROOT")
        self.old_agent_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
        os.environ["DSM_RUNTIME_SECRET_OUTBOX"] = str(Path(self.temp.name) / "controller-outbox")
        os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"] = str(Path(self.temp.name) / "agent-secrets")
        os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(Path(self.temp.name) / "agent-state")

    def tearDown(self):
        for key, old in (("DSM_RUNTIME_SECRET_OUTBOX", self.old_outbox), ("CAPIVARA_RUNTIME_SECRET_ROOT", self.old_agent_secret), ("CAPIVARA_AGENT_STATE_DIR", self.old_agent_state)):
            if old is None: os.environ.pop(key, None)
            else: os.environ[key] = old
        self.temp.cleanup()

    def repo(self):
        repo = RuntimeSecretOutbox(DummyBackend())
        repo._instance_agent = lambda instance_id: "agent-1"
        return repo

    def test_one_time_put_never_exposes_value_in_metadata_or_report(self):
        secret = "top-secret-value"
        repo = self.repo()
        queued = repo.enqueue(instance_id="instance-1", name="SERVER_PASSWORD", action="put", value=secret, requested_by="admin")
        self.assertNotIn(secret, repr(queued))
        self.assertNotIn(secret, repr(repo.list_pending()))
        command = repo.commands_for_agent("agent-1")[0]
        self.assertEqual(command["namespace"], "capivara.runtime.secret")
        self.assertEqual(command["value"]["secret_value"], secret)
        report = apply_configuration(command)
        self.assertEqual(report["status"], "applied")
        self.assertNotIn(secret, repr(report))
        material = Path(os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"]) / "instance-1" / "SERVER_PASSWORD"
        self.assertEqual(material.read_text(), secret)
        self.assertEqual(repo.apply_reports("agent-1", [report]), 1)
        self.assertEqual(repo.list_pending(), [])
        self.assertFalse((Path(os.environ["DSM_RUNTIME_SECRET_OUTBOX"]) / f"{queued['job_id']}.secret").exists())

    def test_rotation_replaces_agent_material_and_revoke_removes_it(self):
        repo = self.repo()
        first = repo.enqueue(instance_id="instance-1", name="TOKEN", action="put", value="first")
        first_command = repo.commands_for_agent("agent-1")[0]
        first_report = apply_configuration(first_command); repo.apply_reports("agent-1", [first_report])
        path = Path(os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"]) / "instance-1" / "TOKEN"
        self.assertEqual(path.read_text(), "first")
        second = repo.enqueue(instance_id="instance-1", name="TOKEN", action="put", value="second")
        second_command = repo.commands_for_agent("agent-1")[0]
        second_report = apply_configuration(second_command); repo.apply_reports("agent-1", [second_report])
        self.assertEqual(path.read_text(), "second")
        revoke = repo.enqueue(instance_id="instance-1", name="TOKEN", action="revoke")
        revoke_command = repo.commands_for_agent("agent-1")[0]
        revoke_report = apply_configuration(revoke_command); repo.apply_reports("agent-1", [revoke_report])
        self.assertFalse(path.exists())
        self.assertNotIn("first", json.dumps([first, second, revoke, first_report, second_report, revoke_report]))
        self.assertNotIn("second", json.dumps([first, second, revoke, first_report, second_report, revoke_report]))


if __name__ == "__main__":
    unittest.main()
