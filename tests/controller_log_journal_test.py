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
