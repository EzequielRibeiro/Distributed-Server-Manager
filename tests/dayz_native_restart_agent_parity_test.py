#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DayZNativeRestartAgentParityTest(unittest.TestCase):

    def test_linux_and_windows_have_native_restart_clients(self):
        linux = ROOT / "agents/linux/runtime/dayz_native_restart_client.py"
        windows = ROOT / "agents/windows/runtime/dayz_native_restart_client.py"

        self.assertTrue(linux.is_file())
        self.assertTrue(windows.is_file())

        for path in (linux, windows):
            source = path.read_text(encoding="utf-8")

            self.assertIn("deadline_minutes_for_due", source)
            self.assertIn("native_restart_plan", source)
            self.assertIn("materialize_shutdown_messages_xml", source)
            self.assertIn("get_instance", source)
            self.assertIn("instance belongs to another Agent", source)
            self.assertIn("native restart command requires DayZ instance", source)

            self.assertNotIn("shell=True", source)
            self.assertNotIn("os.system(", source)

    def test_controller_payload_remains_pathless(self):
        source = (
            ROOT / "database/dayz_native_restart_repository.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '("command_id", "agent_id", "instance_id", "due_at")',
            source,
        )

        self.assertNotIn('"messages_path"', source)
        self.assertNotIn('"xml"', source)

    def test_agents_publish_result_and_accept_command(self):
        for relative in (
            "agents/linux/runtime/agent.py",
            "agents/windows/runtime/agent.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")

            self.assertIn("dayz_native_restart_result", source)
            self.assertIn("dayz_native_restart_command", source)
            self.assertIn("dayz_native_restart_state", source)


if __name__ == "__main__":
    unittest.main()
