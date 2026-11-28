#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents" / "linux" / "privileged" / "console_journal_reader.py"
SPEC = importlib.util.spec_from_file_location("console_journal_reader", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class AgentConsoleJournalReaderTest(unittest.TestCase):
    def test_storage_measurement_is_bounded_to_owned_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "dayz-002"
            root.mkdir(mode=0o710)
            outside = parent / "outside"
            outside.write_bytes(b"outside")
            (root / "alias").symlink_to(outside)
            (parent / "linked").symlink_to(root)
            real_fstat = os.fstat

            def fstat(fd):
                info = real_fstat(fd)
                if info.st_ino == parent.stat().st_ino:
                    return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
                return info

            with patch.object(READER, "INSTANCE_ROOT", parent), patch.object(
                READER.os, "fstat", side_effect=fstat,
            ), patch.object(
                READER.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=root.stat().st_uid),
            ), patch.object(
                READER.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=root.stat().st_gid),
            ):
                self.assertEqual(READER._instance_storage_bytes("dayz-002"), 0)
                (root / "world").write_bytes(b"abc")
                self.assertEqual(READER._instance_storage_bytes("dayz-002"), 3)
                self.assertIsNone(READER._instance_storage_bytes("linked"))
                self.assertIsNone(READER._instance_storage_bytes(".."))
                root.chmod(0o755)
                self.assertIsNone(READER._instance_storage_bytes("dayz-002"))

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
