#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import instance_runtime
import runtime_materialization
from adapters.base import InstanceRuntimeAdapter
from materializers.systemd import SystemdMaterializer, render_unit, unit_path_for_spec
from runtime_spec import RuntimeSpecError, validate_runtime_spec


class FakeAdapter(InstanceRuntimeAdapter):
    name = "systemd"

    def __init__(self, running=False):
        self.running = running

    def status(self, instance):
        return {"adapter": "systemd", "available": True, "active_state": "active" if self.running else "inactive", "running": self.running}

    def start(self, instance):
        self.running = True
        return {"action": "start", "changed": True, "state": self.status(instance)}

    def stop(self, instance):
        self.running = False
        return {"action": "stop", "changed": True, "state": self.status(instance)}

    def restart(self, instance):
        self.running = True
        return {"action": "restart", "changed": True, "state": self.status(instance)}

    def doctor(self, instance):
        return {"status": "healthy", "ready": True, "findings": []}


class B8RuntimeMaterializationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.systemd = self.root / "systemd"
        self.work = self.root / "instance"
        self.work.mkdir()
        self.executable = self.work / "server-bin"
        self.executable.write_text("binary placeholder", encoding="utf-8")
        self.old_systemd = os.environ.get("CAPIVARA_INSTANCE_SYSTEMD_DIR")
        os.environ["CAPIVARA_INSTANCE_SYSTEMD_DIR"] = str(self.systemd)
        self.old_paths = (instance_runtime.STATE_DIR, instance_runtime.INSTANCE_DIR, instance_runtime.RESULT_DIR, instance_runtime.HISTORY_DIR)
        instance_runtime.STATE_DIR = self.root / "state"
        instance_runtime.INSTANCE_DIR = instance_runtime.STATE_DIR / "instances"
        instance_runtime.RESULT_DIR = instance_runtime.STATE_DIR / "instance-results"
        instance_runtime.HISTORY_DIR = instance_runtime.STATE_DIR / "instance-command-history"
        self.config = {"agent_id": "agent-one"}

    def tearDown(self):
        instance_runtime.STATE_DIR, instance_runtime.INSTANCE_DIR, instance_runtime.RESULT_DIR, instance_runtime.HISTORY_DIR = self.old_paths
        if self.old_systemd is None:
            os.environ.pop("CAPIVARA_INSTANCE_SYSTEMD_DIR", None)
        else:
            os.environ["CAPIVARA_INSTANCE_SYSTEMD_DIR"] = self.old_systemd
        self.temp.cleanup()

    def spec(self, **overrides):
        value = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "runtime-one",
            "adapter": "systemd",
            "working_directory": str(self.work),
            "executable": str(self.executable),
            "arguments": ["--port=25000", "value with spaces"],
            "environment": {"CAPIVARA_TEST": "yes"},
            "user": "capivara-instance",
            "desired_state": "running",
        }
        value.update(overrides)
        return value

    def test_runtime_spec_is_structured_and_agent_owned(self):
        normalized = validate_runtime_spec(self.spec(), expected_agent_id="agent-one")
        self.assertEqual(normalized["kind"], "CapivaraInstanceRuntimeSpec")
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(self.spec(agent_id="agent-two"), expected_agent_id="agent-one")
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(self.spec(executable="server-bin"), expected_agent_id="agent-one")
        with self.assertRaises(RuntimeSpecError):
            validate_runtime_spec(self.spec(arguments=["ok\nExecStart=/bin/sh"]), expected_agent_id="agent-one")

    def test_systemd_materializer_is_idempotent_and_refuses_foreign_unit(self):
        calls = []
        runner = lambda command, timeout: (calls.append(list(command)) or (0, "", ""))
        spec = validate_runtime_spec(self.spec(), expected_agent_id="agent-one")
        materializer = SystemdMaterializer(runner=runner)
        first = materializer.apply(spec)
        second = materializer.apply(spec)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(calls, [["systemctl", "daemon-reload"]])
        content = unit_path_for_spec(spec).read_text(encoding="utf-8")
        self.assertIn("X-Capivara-Instance=instance-one", content)
        self.assertIn('"value with spaces"', content)
        unit_path_for_spec(spec).write_text("[Service]\nExecStart=/bin/false\n", encoding="utf-8")
        with self.assertRaises(Exception):
            materializer.apply(spec)

    def test_materialize_registers_instance_and_emits_structured_event(self):
        class Materializer:
            def apply(self, spec):
                return {"action": "materialize", "changed": True, "state": {"exists": True, "owned": True}}
        original = runtime_materialization.resolve_materializer
        runtime_materialization.resolve_materializer = lambda spec: Materializer()
        try:
            result = runtime_materialization.materialize(self.config, self.spec())
        finally:
            runtime_materialization.resolve_materializer = original
        self.assertTrue(result["instance"]["materialized"])
        self.assertEqual(instance_runtime.get_instance("instance-one")["runtime_id"], "runtime-one")
        events = (instance_runtime.STATE_DIR / "events" / "instance-runtime.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(events[-1])["type"], "INSTANCE_RUNTIME_READY")

    def test_reconcile_converges_desired_running_state(self):
        normalized = validate_runtime_spec(self.spec(), expected_agent_id="agent-one")
        instance_runtime.register_instance({**normalized, "observed_state": "stopped", "materialized": True})

        class Materializer:
            def inspect(self, spec):
                return {"exists": True, "owned": True, "matches": True}
        adapter = FakeAdapter(running=False)
        old_materializer = runtime_materialization.resolve_materializer
        old_adapter = runtime_materialization.resolve_adapter
        runtime_materialization.resolve_materializer = lambda spec: Materializer()
        runtime_materialization.resolve_adapter = lambda spec: adapter
        try:
            result = runtime_materialization.reconcile(self.config, "instance-one")
        finally:
            runtime_materialization.resolve_materializer = old_materializer
            runtime_materialization.resolve_adapter = old_adapter
        self.assertTrue(result["changed"])
        self.assertEqual(result["observed_state"], "running")
        self.assertEqual(instance_runtime.get_instance("instance-one")["desired_state"], "running")


if __name__ == "__main__":
    unittest.main()
