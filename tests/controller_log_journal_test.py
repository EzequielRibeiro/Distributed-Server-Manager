#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from dashboard import controller_journal_reader as reader
from dashboard import controller_log_journal_http as http

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ControllerJournalReaderTest(unittest.TestCase):
    def test_limit_is_clamped(self):
        self.assertEqual(reader.clamp_limit(1), 20)
        self.assertEqual(reader.clamp_limit(500), 500)
        self.assertEqual(reader.clamp_limit(99999), 2000)
        self.assertEqual(reader.clamp_limit("bad"), 400)

    def test_journal_command_uses_fixed_units_only(self):
        command = reader.journal_command(500)
        self.assertEqual(command[0], "/usr/bin/journalctl")
        self.assertNotIn("sh", command)
        self.assertNotIn("bash", command)
        self.assertEqual(command.count("-u"), len(reader.CONTROLLER_UNITS))
        for unit in reader.CONTROLLER_UNITS:
            self.assertIn(unit, command)
        self.assertNotIn("dsm-agent.service", command)

    @mock.patch("dashboard.controller_journal_reader.subprocess.run")
    def test_reader_returns_journal_lines(self, run):
        run.return_value = mock.Mock(
            returncode=0,
            stdout="line one\nline two\n",
            stderr="",
        )
        result = reader.read_controller_logs(50)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "systemd-journal")
        self.assertEqual(result["logs"], ["line one", "line two"])
        run.assert_called_once()
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    @mock.patch("dashboard.controller_journal_reader.subprocess.run")
    def test_instance_active_since_reads_current_unit_activation(self, run):
        run.return_value = mock.Mock(
            returncode=0,
            stdout="Mon 2026-09-21 21:05:51 -03\n",
            stderr="",
        )
        value = reader.instance_active_since("cli-000001-minecraft-001")
        self.assertEqual("Mon 2026-09-21 21:05:51 -03", value)
        command = run.call_args.args[0]
        self.assertEqual("/usr/bin/systemctl", command[0])
        self.assertIn("--property=ActiveEnterTimestamp", command)
        self.assertIn(
            "capivara-instance-cli-000001-minecraft-001.service",
            command,
        )
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_instance_snapshot_can_be_bounded_to_current_activation(self):
        command = reader.instance_journal_command(
            "cli-000001-minecraft-001",
            400,
            "Mon 2026-09-21 21:05:51 -03",
        )
        self.assertIn("--since", command)
        index = command.index("--since")
        self.assertEqual(
            "Mon 2026-09-21 21:05:51 -03",
            command[index + 1],
        )
        self.assertIn("--show-cursor", command)

    @mock.patch("dashboard.controller_journal_reader.subprocess.run")
    def test_instance_snapshot_uses_current_activation_timestamp(self, run):
        run.side_effect = [
            mock.Mock(
                returncode=0,
                stdout="Mon 2026-09-21 21:05:51 -03\n",
                stderr="",
            ),
            mock.Mock(
                returncode=0,
                stdout="current run line\n-- cursor: s=abc;i=456\n",
                stderr="",
            ),
        ]
        result = reader.read_instance_logs(
            "cli-000001-minecraft-001",
            400,
        )
        self.assertEqual(["current run line"], result["logs"])
        self.assertEqual("s=abc;i=456", result["cursor"])
        journal_command = run.call_args_list[1].args[0]
        self.assertIn("--since", journal_command)
        self.assertIn(
            "Mon 2026-09-21 21:05:51 -03",
            journal_command,
        )

    def test_instance_follow_command_is_cursor_bounded_and_shell_free(self):
        cursor = "s=abc;i=123"
        command = reader.instance_follow_command("cli-000001-dayz-001", cursor)
        self.assertEqual(reader.JOURNALCTL, command[0])
        self.assertIn("--follow", command)
        self.assertIn("--after-cursor", command)
        self.assertIn(cursor, command)
        self.assertIn("capivara-instance-cli-000001-dayz-001.service", command)
        self.assertNotIn("sh", command)
        self.assertNotIn("bash", command)

    @mock.patch("dashboard.controller_journal_reader.subprocess.run")
    def test_instance_snapshot_extracts_journal_cursor(self, run):
        run.return_value = mock.Mock(
            returncode=0,
            stdout="line one\n-- cursor: s=abc;i=123\n",
            stderr="",
        )
        result = reader.read_instance_logs("cli-000001-dayz-001", 50)
        self.assertEqual(["line one"], result["logs"])
        self.assertEqual("s=abc;i=123", result["cursor"])
        self.assertIn("--show-cursor", run.call_args.args[0])

    def test_http_limit_matches_reader_contract(self):
        self.assertEqual(http._limit(1), 20)
        self.assertEqual(http._limit(2001), 2000)
        self.assertEqual(http._limit("bad"), 400)

    def test_controller_contract_has_no_legacy_file_fallback(self):
        journal_http = (ROOT / "dashboard" / "controller_log_journal_http.py").read_text(encoding="utf-8")
        composition = (ROOT / "dashboard" / "server_part17.py").read_text(encoding="utf-8")
        unit = (ROOT / "systemd" / "dsm-controller-log-reader.service").read_text(encoding="utf-8")
        dashboard_unit = (ROOT / "systemd" / "dsm-dashboard.service").read_text(encoding="utf-8")

        for legacy in ("dashboard.log", "dsm-dashboard.service.log", "dsm.log"):
            self.assertNotIn(legacy, journal_http)

        self.assertIn("install_controller_log_journal_http", composition)
        self.assertIn("SupplementaryGroups=systemd-journal", unit)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", unit)
        self.assertIn("dsm-controller-log-reader.service", dashboard_unit)
        self.assertNotIn("SupplementaryGroups=systemd-journal", dashboard_unit)


if __name__ == "__main__":
    unittest.main()
