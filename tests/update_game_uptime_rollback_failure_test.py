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

    def test_real_restart_helpers_propagate_errors_inside_conditional_recovery(self):
        cases = {
            "service_reload": ["daemon-reload"],
            "service_start": ["daemon-reload", "start dsm-dashboard.service"],
            "game_reload": ["daemon-reload"],
            "game_start": ["daemon-reload", "start capivara-instance-test-dayz-001.service"],
            "game_wait": ["daemon-reload", "start capivara-instance-test-dayz-001.service", "wait"],
        }
        # Calling functions as an `if` condition disables Bash's implicit
        # errexit in nested function bodies. Check explicit error propagation.
        script = r"""
source "$1"
trap - ERR
CASE="$2"
CALLS="$3"
SYSTEMD_ENABLED=1
RESTORE_SERVICES=(dsm-dashboard.service)
ACTIVE_GAME_UNITS=(capivara-instance-test-dayz-001.service)
systemctl() {
  printf '%s\n' "$*" >> "$CALLS"
  if [[ "$1" == daemon-reload && "$CASE" == *reload ]]; then return 18; fi
  if [[ "$1" == start && "$CASE" == *start ]]; then return 19; fi
  return 0
}
wait_for_game_instance_active() {
  printf 'wait\n' >> "$CALLS"
  if [[ "$CASE" == game_wait ]]; then return 20; fi
  return 0
}
if [[ "$CASE" == service_* ]]; then
  if restart_services; then exit 90; fi
else
  if restart_game_instances; then exit 91; fi
fi
printf 'REJECTED\n'
"""
        for case, expected_calls in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="dsm928-restart-guards-") as temp:
                calls = Path(temp) / "calls"
                result = subprocess.run(
                    ["bash", "-c", script, "test", str(ROOT / "update.sh"), case, str(calls)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("REJECTED", result.stdout)
                self.assertEqual(calls.read_text().splitlines(), expected_calls)
                self.assertIn("[ERROR]", result.stderr)

    def test_recovery_attempts_every_originally_active_service_and_game(self):
        # A single failed unit must not prevent recovery of subsequent units.
        cases = {
            "service_first_failure": (
                ["daemon-reload", "start dsm-dashboard.service",
                 "start dsm-dashboard-worker.service"], 1),
            "game_first_failure": (
                ["daemon-reload", "start capivara-instance-test-dayz-001.service",
                 "start capivara-instance-test-minecraft-002.service",
                 "wait capivara-instance-test-minecraft-002.service"], 1),
            "game_first_readiness_failure": (
                ["daemon-reload", "start capivara-instance-test-dayz-001.service",
                 "wait capivara-instance-test-dayz-001.service",
                 "start capivara-instance-test-minecraft-002.service",
                 "wait capivara-instance-test-minecraft-002.service"], 1),
            "service_success": (
                ["daemon-reload", "start dsm-dashboard.service",
                 "start dsm-dashboard-worker.service"], 0),
            "game_success": (
                ["daemon-reload", "start capivara-instance-test-dayz-001.service",
                 "wait capivara-instance-test-dayz-001.service",
                 "start capivara-instance-test-minecraft-002.service",
                 "wait capivara-instance-test-minecraft-002.service"], 0),
        }
        script = r"""
source "$1"
trap - ERR
CASE="$2"
CALLS="$3"
SYSTEMD_ENABLED=1
RESTORE_SERVICES=(dsm-dashboard.service dsm-dashboard-worker.service)
ACTIVE_GAME_UNITS=(capivara-instance-test-dayz-001.service capivara-instance-test-minecraft-002.service)
systemctl() {
    printf '%s\n' "$*" >> "$CALLS"
    if [[ "$CASE" == service_first_failure && "$*" == "start dsm-dashboard.service" ]]; then return 30; fi
    if [[ "$CASE" == game_first_failure && "$*" == "start capivara-instance-test-dayz-001.service" ]]; then return 40; fi
    return 0
}
wait_for_game_instance_active() {
    printf 'wait %s\n' "$1" >> "$CALLS"
    if [[ "$CASE" == game_first_readiness_failure && "$1" == capivara-instance-test-dayz-001.service ]]; then return 50; fi
    return 0
}
RESULT=0
if [[ "$CASE" == service_* ]]; then
    restart_services || RESULT=$?
else
    restart_game_instances || RESULT=$?
fi
printf 'RECOVERY_RESULT=%s\n' "$RESULT"
"""
        for case, (expected_calls, expected_result) in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="dsm928-multi-recovery-") as temp:
                record = Path(temp) / "calls"
                completed = subprocess.run(
                    ["bash", "-c", script, "test", str(ROOT / "update.sh"), case, str(record)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(record.read_text().splitlines(), expected_calls)
                self.assertIn(f"RECOVERY_RESULT={expected_result}", completed.stdout)
                if expected_result:
                    self.assertIn("[ERROR]", completed.stderr)

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
