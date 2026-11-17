"""Regression tests for bounded journalctl failure diagnostics."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents/linux/runtime"))
from systemd_journal_reader import read_systemd_transitions


class JournalExitDiagnosticsTest(unittest.TestCase):
    def test_failed_runner_exposes_exit_code_not_stderr(self):
        def runner(args):
            return SimpleNamespace(returncode=7, stdout="secret stderr content")
        with self.assertRaisesRegex(RuntimeError, r"journal query failed \(exit_code=7\)") as error:
            read_systemd_transitions(
                "cli-000001-dayz-001",
                since="2026-10-15T11:23:00Z",
                until="2026-10-15T11:26:00Z",
                runner=runner,
            )
        self.assertNotIn("secret", str(error.exception))

    def test_successful_empty_runner(self):
        result = read_systemd_transitions(
            "cli-000001-dayz-001",
            since="2026-10-15T11:23:00Z",
            until="2026-10-15T11:26:00Z",
            runner=lambda args: SimpleNamespace(returncode=0, stdout=""),
        )
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
