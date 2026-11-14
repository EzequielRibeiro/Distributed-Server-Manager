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

    def test_pre_file_recovery_attempts_both_steps_and_exposes_partial_failure(self):
        for services_rc, games_rc in ((0, 0), (12, 0), (0, 14), (12, 14)):
            with self.subTest(services_rc=services_rc, games_rc=games_rc):
                script = r"""
source "$1"
trap - ERR
collect_failure_diagnostics() { :; }
cleanup_partial_backup() { :; }
RECOVERY_CALLS="$2"
SERVICE_RC="$3"
GAME_RC="$4"
restart_services() { printf 'services\n' >> "$RECOVERY_CALLS"; return "$SERVICE_RC"; }
restart_game_instances() { printf 'games\n' >> "$RECOVERY_CALLS"; return "$GAME_RC"; }
UPDATE_TRANSACTION_STARTED=1
UPDATE_FILES_STARTED=0
BACKUP_FILE=""
update_failed 999
"""
                with tempfile.TemporaryDirectory(prefix="dsm-rollback-early-") as temp:
                    record = Path(temp) / "recovery-calls"
                    result = subprocess.run(
                        ["bash", "-c", script, "test", str(ROOT / "update.sh"),
                         str(record), str(services_rc), str(games_rc)],
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(record.read_text(), "services\ngames\n")
                    if services_rc or games_rc:
                        self.assertIn("CRITICAL: pre-update service/game recovery incomplete", result.stderr)
                        self.assertIn(f"services={services_rc}, games={games_rc}", result.stderr)
                    else:
                        self.assertNotIn("CRITICAL: pre-update service/game recovery incomplete", result.stderr)

    def test_pre_transaction_failure_does_not_attempt_restart(self):
        script = """
source "$1"
trap - ERR
collect_failure_diagnostics() { :; }
cleanup_partial_backup() { :; }
restart_services() { echo SHOULD_NOT_START_SERVICES; return 2; }
restart_game_instances() { echo SHOULD_NOT_START_GAMES; return 3; }
UPDATE_TRANSACTION_STARTED=0
UPDATE_FILES_STARTED=0
BACKUP_FILE=""
update_failed 999
"""
        result = subprocess.run(
            ["bash", "-c", script, "test", str(ROOT / "update.sh")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("SHOULD_NOT_START", result.stdout + result.stderr)

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
