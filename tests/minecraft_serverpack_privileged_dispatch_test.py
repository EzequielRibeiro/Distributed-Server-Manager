"""Exercise the real root materializer request/result protocol without touching production."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "agents/linux/runtime"
COMMON = ROOT / "agents/common"
for directory in (str(LINUX), str(COMMON)):
    if directory not in sys.path:
        sys.path.insert(0, directory)


class ServerPackPrivilegedDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Avoid platform-specific catalog modules cached by the Windows tests.
        policy_path = LINUX / "catalog_runtime_policy.py"
        policy_spec = importlib.util.spec_from_file_location("pr920_linux_catalog_policy", policy_path)
        policy = importlib.util.module_from_spec(policy_spec)
        policy_spec.loader.exec_module(policy)
        spec = importlib.util.spec_from_file_location(
            "pr920_privileged_dispatch_helper",
            ROOT / "agents/linux/privileged/materialize_instance.py",
        )
        cls.helper = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"catalog_runtime_policy": policy}):
            spec.loader.exec_module(cls.helper)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request_root = self.root / "privileged-materialization"
        self.request_root.mkdir()
        self.config_path = self.root / "agent.json"
        self.config_path.write_text(json.dumps({"agent_id": "pr920-isolated-agent"}))
        self.iid = "pr920-disposable"
        self.spec = {
            "instance_id": self.iid,
            "agent_id": "pr920-isolated-agent",
            "game_id": "minecraft",
            "environment_id": "minecraft.java.neoforge",
            "instance_state_root": str(self.root / self.iid),
            "working_directory": str(self.root / self.iid / "runtime"),
        }
        self.request = {
            "kind": "CapivaraPrivilegedMaterializationRequest",
            "schema_version": 1,
            "action": "minecraft-serverpack-swap-phase",
            "phase": "recover",
            "agent_id": "pr920-isolated-agent",
            "instance_id": self.iid,
            "spec": self.spec,
        }
        self.patches = [
            patch.object(self.helper, "REQUEST_ROOT", self.request_root),
            patch.object(self.helper, "CONFIG_PATH", self.config_path),
            patch.object(self.helper, "validate_runtime_spec", return_value=self.spec),
            patch.object(self.helper, "resolve_materializer", return_value=object()),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _save(self):
        (self.request_root / f"{self.iid}.request.json").write_text(json.dumps(self.request))

    def test_root_dispatches_recovery_and_writes_matching_result(self):
        self._save()
        with patch.object(self.helper, "_serverpack_require_inactive") as inactive, patch.object(
            self.helper, "_serverpack_swap_phase", return_value={"status": "recovered"}
        ) as operation:
            result = self.helper.run(self.iid)
        inactive.assert_called_once_with(self.iid)
        operation.assert_called_once()
        self.assertEqual(operation.call_args.kwargs["phase"], "recover")
        self.assertEqual(result["operation"]["status"], "recovered")
        self.assertEqual(
            json.loads((self.request_root / f"{self.iid}.result.json").read_text())["operation"],
            {"status": "recovered"},
        )

    def test_denies_cross_agent_request_before_dispatch(self):
        self.request["agent_id"] = "foreign-agent"
        self._save()
        with patch.object(self.helper, "_serverpack_swap_phase") as operation:
            with self.assertRaisesRegex(PermissionError, "another Agent"):
                self.helper.run(self.iid)
        operation.assert_not_called()

    def test_denies_active_unit_before_dispatch(self):
        self._save()
        with patch.object(
            self.helper, "_serverpack_require_inactive",
            side_effect=RuntimeError("Server Pack migration requires an inactive loaded instance unit"),
        ), patch.object(self.helper, "_serverpack_swap_phase") as operation:
            with self.assertRaisesRegex(RuntimeError, "inactive loaded"):
                self.helper.run(self.iid)
        operation.assert_not_called()

    def test_denies_mismatched_instance_in_request(self):
        self.request["instance_id"] = "other-instance"
        self._save()
        with patch.object(self.helper, "_serverpack_swap_phase") as operation:
            with self.assertRaisesRegex(RuntimeError, "instance_id mismatch"):
                self.helper.run(self.iid)
        operation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
