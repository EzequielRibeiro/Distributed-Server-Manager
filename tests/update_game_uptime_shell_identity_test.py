"""Isolated shell tests for #928 identity capture and rollback fail-closed behavior."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShellIdentityTest(unittest.TestCase):
    def run_shell(self, body):
        script = """
source "$1"
trap - ERR
ACTIVE_GAME_UNITS=(capivara-instance-demo.service)
systemctl() {
    [[ "$1" == show ]] || return 1
    case "$3" in
        --property=ActiveState) echo active ;;
        --property=MainPID) echo "${TEST_PID:-3210}" ;;
        --property=ExecMainStartTimestampMonotonic) echo 456789 ;;
        *) return 1 ;;
    esac
}
""" + body
        return subprocess.run(["bash", "-c", script, "test", str(ROOT / "update.sh")],
                              capture_output=True, text=True, timeout=10)

    def test_snapshot_and_verify_unchanged(self):
        r = self.run_shell("capture_no_drain_process_identities && verify_no_drain_process_identities")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_pid_change_is_rejected(self):
        r = self.run_shell('capture_no_drain_process_identities || exit 1; TEST_PID=3211; ! verify_no_drain_process_identities')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_rollback_without_gate_never_calls_callback(self):
        r = self.run_shell("""
capture_no_drain_process_identities || exit 1
rollback_no_drain_disposable_fixture() { echo CALLBACK_CALLED; }
verify_no_drain_rollback rollback_no_drain_disposable_fixture
""")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn("CALLBACK_CALLED", r.stdout)

    def test_rollback_rechecks_identity(self):
        r = self.run_shell("""
capture_no_drain_process_identities || exit 1
NO_DRAIN_DISPOSABLE_ROLLBACK_ENABLED=1
rollback_no_drain_disposable_fixture() { TEST_PID=3211; }
verify_no_drain_rollback rollback_no_drain_disposable_fixture
""")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("manual recovery required", r.stderr)


if __name__ == "__main__":
    unittest.main()
