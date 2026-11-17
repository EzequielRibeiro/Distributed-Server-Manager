"""Exercise the Agent-to-materializer protocol without invoking real systemd."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents/linux/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import privileged_materialization as bridge


class PrivilegedServerPackBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request_patch = patch.object(bridge, "_request_root", return_value=self.root)
        self.request_patch.start()
        self.addCleanup(self.request_patch.stop)
        self.spec = {"instance_id": "isolated-minecraft", "agent_id": "agent-test"}

    def _fake_systemd(self, args, **kwargs):
        request = json.loads((self.root / "isolated-minecraft.request.json").read_text())
        self.request = request
        (self.root / "isolated-minecraft.result.json").write_text(json.dumps({
            "status": "completed", "operation": {"status": "ok", "phase": request.get("phase")},
        }))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    def test_prepare_inputs_protocol(self):
        with patch.object(bridge.subprocess, "run", side_effect=self._fake_systemd) as run:
            result = bridge._invoke("minecraft-serverpack-prepare-inputs", self.spec,
                                    migration={"transfer_id": "transfer-test"},
                                    selection={"runtime_definition": "minecraft.java.neoforge"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.request["action"], "minecraft-serverpack-prepare-inputs")
        self.assertEqual(self.request["instance_id"], self.spec["instance_id"])
        self.assertEqual(self.request["migration"]["transfer_id"], "transfer-test")
        self.assertEqual(self.request["selection"]["runtime_definition"], "minecraft.java.neoforge")
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)

    def test_commit_protocol_carries_readiness_evidence(self):
        evidence = {"passed": True, "migration_plan_sha256": "b" * 64,
                    "target_loader_version": "26.1.2.109", "serverpack_mod_count": 1}
        with patch.object(bridge.subprocess, "run", side_effect=self._fake_systemd) as run:
            result = bridge._invoke("minecraft-serverpack-swap-phase", self.spec,
                                    phase="commit", readiness_evidence=evidence)
        self.assertEqual(result["phase"], "commit")
        self.assertEqual(self.request["readiness_evidence"], evidence)
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)

    def test_missing_result_fails_closed(self):
        with patch.object(bridge.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stderr="", stdout="")):
            with self.assertRaisesRegex(RuntimeError, "no valid result"):
                bridge._invoke("minecraft-serverpack-swap-phase", self.spec, phase="recover")

    def test_helper_failure_propagates(self):
        def failure(args, **kwargs):
            (self.root / "isolated-minecraft.result.json").write_text(json.dumps({
                "status": "failed", "error": "simulated helper rejection",
            }))
            return SimpleNamespace(returncode=1, stderr="", stdout="")
        with patch.object(bridge.subprocess, "run", side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, "simulated helper rejection"):
                bridge._invoke("minecraft-serverpack-swap-phase", self.spec, phase="switch")


if __name__ == "__main__":
    unittest.main()
