"""Windows relocation fence tests, run separately with windows/runtime in PYTHONPATH."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import instance_runtime
import relocation_fence


class WindowsRelocationFenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(instance_runtime, "STATE_DIR", Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(
            instance_runtime, "_owned",
            return_value={"instance_id": "mc-001", "agent_id": "win-agent",
                          "runtime_id": "capivara-mc-001"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_windows_service_cannot_restart_until_unfence(self):
        def run(*args):
            if args[0] == "qc":
                return SimpleNamespace(returncode=0, stdout="START_TYPE : 2 AUTO_START", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(relocation_fence, "_run", side_effect=run) as runner, patch.object(
                relocation_fence, "_query",
                side_effect=[{"available": True, "active_state": "active"},
                             {"available": True, "active_state": "inactive"},
                             {"available": True, "active_state": "inactive"}]), patch.object(
                instance_runtime, "lifecycle",
                return_value={"observed_state": "stopped"}) as stop:
            result = relocation_fence.fence(
                {"agent_id": "win-agent"}, "mc-001", "relocation:123")
            self.assertTrue(result["fenced"])
            self.assertTrue(relocation_fence.locked("mc-001"))
            stop.assert_called_once()
            self.assertTrue(relocation_fence.locked("mc-001"))
            self.assertFalse(relocation_fence.unfence(
                {"agent_id": "win-agent"}, "mc-001", "relocation:123")["fenced"])
            self.assertFalse(relocation_fence.locked("mc-001"))
            command_calls = [call.args for call in runner.call_args_list]
            self.assertIn(("config", "capivara-mc-001", "start=", "disabled"), command_calls)
            self.assertIn(("config", "capivara-mc-001", "start=", "auto"), command_calls)

    def test_locked_marker_blocks_agent_start_and_restart(self):
        path, _ = relocation_fence._state("mc-001")
        instance_runtime._write(path, {"actor": "relocation:abc", "phase": "fenced"})
        for action in ("start", "restart"):
            with self.assertRaises(PermissionError):
                instance_runtime.lifecycle({"agent_id": "win-agent"}, "mc-001", action)

    def test_unfence_rejects_wrong_relocation_actor(self):
        path, _ = relocation_fence._state("mc-001")
        instance_runtime._write(path, {"actor": "relocation:a", "service": "capivara-mc-001",
                                       "previous": "AUTO_START"})
        with self.assertRaises(PermissionError):
            relocation_fence.unfence(
                {"agent_id": "win-agent"}, "mc-001", "relocation:other")
        self.assertTrue(relocation_fence.locked("mc-001"))


if __name__ == "__main__":
    unittest.main()
