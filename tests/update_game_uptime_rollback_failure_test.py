"""Exercise the real updater failure handler without touching host services."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpdateFailureRecoveryTests(unittest.TestCase):
    def test_failed_rollback_reports_critical_error_and_backup(self):
        with tempfile.TemporaryDirectory(prefix="dsm-rollback-test-") as temp:
            backup = Path(temp) / "pre-update.tar.gz"
            backup.write_bytes(b"placeholder: rollback is mocked")
            script = """
source "$1"
trap - ERR
collect_failure_diagnostics() { :; }
cleanup_partial_backup() { :; }
rollback() { return 23; }
UPDATE_TRANSACTION_STARTED=1
UPDATE_FILES_STARTED=1
BACKUP_FILE="$2"
update_failed 999
"""
            result = subprocess.run(
                ["bash", "-c", script, "test", str(ROOT / "update.sh"), str(backup)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("CRITICAL: automatic rollback failed", result.stderr)
            self.assertIn(str(backup), result.stderr)
            self.assertTrue(backup.exists(), "Recovery backup must not be removed")

    def test_missing_backup_after_file_replacement_is_critical(self):
        script = """
source "$1"
trap - ERR
collect_failure_diagnostics() { :; }
cleanup_partial_backup() { :; }
UPDATE_TRANSACTION_STARTED=1
UPDATE_FILES_STARTED=1
BACKUP_FILE="/tmp/dsm928-definitely-missing-backup"
update_failed 999
"""
        result = subprocess.run(
            ["bash", "-c", script, "test", str(ROOT / "update.sh")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("CRITICAL: files changed but no rollback backup is available", result.stderr)

    def test_successful_rollback_does_not_report_critical_error(self):
        with tempfile.TemporaryDirectory(prefix="dsm-rollback-test-") as temp:
            backup = Path(temp) / "pre-update.tar.gz"
            backup.write_bytes(b"placeholder")
            script = """
source "$1"
trap - ERR
collect_failure_diagnostics() { :; }
cleanup_partial_backup() { :; }
rollback() { return 0; }
UPDATE_TRANSACTION_STARTED=1
UPDATE_FILES_STARTED=1
BACKUP_FILE="$2"
update_failed 999
"""
            result = subprocess.run(
                ["bash", "-c", script, "test", str(ROOT / "update.sh"), str(backup)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("CRITICAL: automatic rollback failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
