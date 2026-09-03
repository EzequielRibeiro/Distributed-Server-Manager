#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "agents" / "windows" / "service" / "uninstall-agent.ps1"


class WindowsUninstallPreservationTelemetryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")

    def test_captures_preservation_state_before_cleanup(self):
        self.assertIn("$InstancesPresentBefore = Test-Path", self.script)
        self.assertIn("$BackupsPresentBefore = Test-Path", self.script)

    def test_reports_before_and_after_state(self):
        self.assertIn("instances_present_before = $InstancesPresentBefore", self.script)
        self.assertIn("instances_present_after = $instancesPresentAfter", self.script)
        self.assertIn("backups_present_before = $BackupsPresentBefore", self.script)
        self.assertIn("backups_present_after = $backupsPresentAfter", self.script)

    def test_preserved_requires_preexisting_and_remaining_data(self):
        self.assertIn(
            "$InstancesPresentBefore -and $instancesPresentAfter",
            self.script,
        )
        self.assertIn(
            "$BackupsPresentBefore -and $backupsPresentAfter",
            self.script,
        )

    def test_terminal_report_includes_uninstall_mode(self):
        self.assertIn("mode = $UninstallMode", self.script)
        self.assertIn(
            '$UninstallMode = if ($Purge) { "purge" } else { "preserve-data" }',
            self.script,
        )


if __name__ == "__main__":
    unittest.main()
