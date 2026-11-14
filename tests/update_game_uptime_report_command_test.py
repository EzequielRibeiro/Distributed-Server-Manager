"""#928 read-only updater diagnostic: never performs host mutations or authorizes no-drain."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NoDrainDiagnosticCommandTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsm928-report-cli-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.installed = self.workspace / "installed"
        self.target = self.workspace / "target"
        for root in (self.installed, self.target):
            (root / "dashboard/web").mkdir(parents=True)
            (root / "dashboard/web/style.css").write_text("new" if root == self.target else "old")
        self.marker = self.installed / "must-stay-unchanged"
        self.marker.write_text("preserved")
        (self.target / self.marker.name).write_text("preserved")
        fake_bin = self.workspace / "bin"
        fake_bin.mkdir()
        shim = fake_bin / "systemctl"
        shim.write_text("#!/bin/sh\n# No units active in this synthetic inventory.\nexit 0\n")
        shim.chmod(0o755)
        self.environment = dict(os.environ)
        self.environment["PATH"] = str(fake_bin) + os.pathsep + os.environ["PATH"]

    def run_diagnostic(self, *options, target=None):
        # Sourcing deliberately prevents invoking the script's normal main().
        # A successful diagnostic *always* exits 2 before require_root.
        script = 'source "$1"; trap - ERR; INSTALL_DIR="$2"; shift 2; main "$@"'
        return subprocess.run(
            ["bash", "-c", script, "test", str(ROOT / "update.sh"),
             str(self.installed), *options,
             str(self.target if target is None else target)],
            capture_output=True, text=True, timeout=15, env=self.environment,
            cwd=self.workspace,
        )

    def test_report_is_read_only_and_never_authorizes_drain_bypass(self):
        before = {str(path.relative_to(self.workspace))
                  for path in self.workspace.rglob("*")}
        result = self.run_diagnostic("--no-drain-report")
        self.assertEqual(result.returncode, 2, result.stderr)
        values = [json.loads(line) for line in result.stdout.splitlines()
                  if line.startswith('{"kind":')]
        self.assertEqual(len(values), 1, result.stdout)
        report = values[0]
        self.assertEqual(report["kind"], "CapivaraDSMNoDrainPreflight")
        self.assertFalse(report["live_no_drain_authorized"])
        self.assertTrue(report["current_updater_drains_active_games"])
        self.assertEqual(report["classification"], "review_only")
        self.assertFalse(report["compatibility_gate"]["compatible_for_further_rehearsal"])
        self.assertIn("Diagnostic only", result.stderr)
        self.assertEqual(self.marker.read_text(), "preserved")
        after = {str(path.relative_to(self.workspace))
                 for path in self.workspace.rglob("*")}
        self.assertEqual(before, after, "read-only command changed test workspace")

    def test_report_does_not_become_update_when_other_flags_present(self):
        for options in (("--yes", "--no-drain-report"),
                        ("--no-backup", "--no-drain-report", "--yes"),
                        ("--allow-downgrade", "--no-drain-report")):
            with self.subTest(options=options):
                result = self.run_diagnostic(*options)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Diagnostic only", result.stderr)
                self.assertEqual(self.marker.read_text(), "preserved")

    def test_missing_target_and_symlinked_target_fail_before_python(self):
        missing = self.workspace / "missing-target"
        alias = self.workspace / "target-link"
        alias.symlink_to(self.target, target_is_directory=True)
        for target in (missing, alias):
            with self.subTest(target=target):
                result = self.run_diagnostic("--no-drain-report", target=target)
                self.assertEqual(result.returncode, 2)
                self.assertIn("requires a safe target directory", result.stderr)
                self.assertNotIn('{"kind":', result.stdout)
        self.assertEqual(self.marker.read_text(), "preserved")

    def test_no_drain_still_rejected_even_if_report_flag_is_present(self):
        for options in (("--no-drain", "--no-drain-report"),
                        ("--no-drain-report", "--no-drain")):
            with self.subTest(options=options):
                result = self.run_diagnostic(*options)
                self.assertEqual(result.returncode, 2)
                self.assertIn("not yet homologated", result.stderr)
                self.assertNotIn('{"kind":', result.stdout)


if __name__ == "__main__":
    unittest.main()
