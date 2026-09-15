#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents/windows/runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
MODULE_PATH = RUNTIME / "console_client.py"


def load_module():
    spec = importlib.util.spec_from_file_location("windows_console_state_tested", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONSOLE = load_module()


class WindowsConsoleStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.logs = self.state / "runtime-processes" / "logs"
        self.logs.mkdir(parents=True)
        self.patchers = [
            mock.patch.object(CONSOLE, "STATE_DIR", self.state),
            mock.patch.object(CONSOLE, "PROCESS_LOG_DIR", self.logs),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def _snapshot(self, record: dict) -> list[dict]:
        with mock.patch.object(
            CONSOLE.instance_runtime,
            "list_instances",
            return_value=[{"instance_id": record["instance_id"]}],
        ), mock.patch.object(
            CONSOLE.instance_runtime,
            "get_instance",
            return_value=record,
        ):
            return CONSOLE.console_state({"agent_id": record["agent_id"]})

    def test_windows_process_log_is_heartbeat_fallback_without_command_console(self) -> None:
        log = self.logs / "instance-1.log"
        log.write_text("old\nready\n", encoding="utf-8")
        result = self._snapshot({
            "instance_id": "instance-1",
            "agent_id": "agent-1",
            "adapter": "windows-process",
        })
        self.assertEqual(1, len(result))
        self.assertEqual(["old", "ready"], result[0]["output"])
        self.assertEqual("windows-process-log", result[0]["transport"])
        self.assertFalse(result[0]["supported"])

    def test_configured_output_cannot_escape_agent_state_root(self) -> None:
        outside = Path(self.temp.name) / "secret.txt"
        outside.write_text("must-not-leak\n", encoding="utf-8")
        result = self._snapshot({
            "instance_id": "instance-2",
            "agent_id": "agent-1",
            "adapter": "windows-service",
            "console": {
                "supported": True,
                "transport": "exec",
                "output_file": str(outside),
            },
        })
        self.assertEqual(1, len(result))
        self.assertEqual([], result[0]["output"])
        self.assertEqual("exec", result[0]["transport"])

    def test_configured_output_inside_agent_state_remains_supported(self) -> None:
        output = self.state / "console" / "instance-3.log"
        output.parent.mkdir(parents=True)
        output.write_text("line-one\nline-two\n", encoding="utf-8")
        result = self._snapshot({
            "instance_id": "instance-3",
            "agent_id": "agent-1",
            "adapter": "windows-service",
            "console": {
                "supported": True,
                "transport": "exec",
                "output_file": str(output),
            },
        })
        self.assertEqual(["line-one", "line-two"], result[0]["output"])
        self.assertEqual("exec", result[0]["transport"])
        self.assertTrue(result[0]["supported"])


if __name__ == "__main__":
    unittest.main()
