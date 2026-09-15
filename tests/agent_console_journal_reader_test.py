#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents" / "linux" / "privileged" / "console_journal_reader.py"
SPEC = importlib.util.spec_from_file_location("console_journal_reader", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class AgentConsoleJournalReaderTest(unittest.TestCase):
    def test_application_output_uses_systemd_unit(self) -> None:
        event = READER._event(
            {
                "_SYSTEMD_UNIT": "capivara-instance-cli-000001-dayz-001.service",
                "MESSAGE": "DayZ ready",
                "__CURSOR": "cursor-app",
            }
        )
        self.assertIsNotNone(event)
        self.assertEqual("cli-000001-dayz-001", event["instance_id"])
        self.assertEqual("DayZ ready", event["line"])

    def test_systemd_manager_stop_message_uses_unit_field(self) -> None:
        event = READER._event(
            {
                "_SYSTEMD_UNIT": "init.scope",
                "UNIT": "capivara-instance-cli-000001-dayz-001.service",
                "MESSAGE": "Stopping Capivara instance cli-000001-dayz-001...",
                "__CURSOR": "cursor-stop",
            }
        )
        self.assertIsNotNone(event)
        self.assertEqual("cli-000001-dayz-001", event["instance_id"])

    def test_systemd_manager_start_message_uses_object_unit_field(self) -> None:
        event = READER._event(
            {
                "_SYSTEMD_UNIT": "init.scope",
                "OBJECT_SYSTEMD_UNIT": "capivara-instance-cli-000001-dayz-001.service",
                "MESSAGE": "Started Capivara instance cli-000001-dayz-001.",
                "__CURSOR": "cursor-start",
            }
        )
        self.assertIsNotNone(event)
        self.assertEqual("cli-000001-dayz-001", event["instance_id"])

    def test_non_instance_unit_remains_denied(self) -> None:
        event = READER._event(
            {
                "_SYSTEMD_UNIT": "init.scope",
                "UNIT": "ssh.service",
                "MESSAGE": "Started OpenSSH server.",
            }
        )
        self.assertIsNone(event)


if __name__ == "__main__":
    unittest.main()
