"""Linux relocation fence tests, run separately with linux/runtime first in PYTHONPATH."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import instance_runtime
import relocation_fence


class LinuxRelocationFenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        state_patch = patch.object(instance_runtime, "STATE_DIR", self.state)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.record = {"instance_id": "dayz-001", "agent_id": "source-agent"}
        owner_patch = patch.object(instance_runtime, "_owned", return_value=self.record)
        owner_patch.start()
        self.addCleanup(owner_patch.stop)

    def test_disable_then_stop_and_restore_original_startup_mode(self):
        states = [{"available": True, "running": True},
                  {"available": True, "running": False}]
        with patch.object(relocation_fence, "_default_runner",
                          return_value=(0, "enabled", "")), patch(
                "privileged_materialization.disable_relocation_source") as disable, patch(
                "privileged_materialization.restore_relocation_source") as restore, patch.object(
                relocation_fence.SystemdAdapter, "status",
                side_effect=states + [states[-1]]) as status, patch.object(
                instance_runtime, "lifecycle",
                return_value={"observed_state": "stopped"}) as stop:
            result = relocation_fence.fence(
                {"agent_id": "source-agent"}, "dayz-001", "relocation:abc123")
            self.assertTrue(result["fenced"])
            self.assertTrue(relocation_fence.locked("dayz-001"))
            disable.assert_called_once()
            stop.assert_called_once_with({"agent_id": "source-agent"}, "dayz-001", "stop")
            self.assertTrue(relocation_fence.locked("dayz-001"))
            recovered = relocation_fence.unfence(
                {"agent_id": "source-agent"}, "dayz-001", "relocation:abc123")
            self.assertFalse(recovered["fenced"])
            restore.assert_called_once()
        self.assertFalse(relocation_fence.locked("dayz-001"))

    def test_locked_marker_blocks_agent_start_and_restart(self):
        path, _ = relocation_fence._state("dayz-001")
        instance_runtime._write(path, {"actor": "relocation:abc", "phase": "fenced"})
        for action in ("start", "restart"):
            with self.assertRaises(PermissionError):
                instance_runtime.lifecycle({"agent_id": "source-agent"}, "dayz-001", action)

    def test_uncertain_privileged_failure_keeps_durable_start_guard(self):
        with patch.object(relocation_fence, "_default_runner",
                          return_value=(0, "disabled", "")), patch(
                "privileged_materialization.disable_relocation_source",
                side_effect=RuntimeError("privileged helper unavailable")):
            with self.assertRaisesRegex(RuntimeError, "privileged helper"):
                relocation_fence.fence(
                    {"agent_id": "source-agent"}, "dayz-001", "relocation:abc123")
        self.assertTrue(relocation_fence.locked("dayz-001"))
        with self.assertRaises(PermissionError):
            relocation_fence.unfence({"agent_id": "source-agent"},
                                     "dayz-001", "relocation:someone-else")


if __name__ == "__main__":
    unittest.main()
