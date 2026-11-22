"""DSM #928: one grouped admission-only proof for two privileged Agent helpers.

No root service, game, user files, Agent host, network or updater is used.
No claim that an already-running helper has stopped is made.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in (
    ROOT / "agents/linux/runtime",
    ROOT / "agents/linux/privileged",
    ROOT / "agents/common",
):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import game_uptime_privileged_admission as admission


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivilegedHelperAdmissionTests(unittest.TestCase):
    def test_two_root_helpers_refuse_new_mutations_without_touching_games(self):
        from unittest.mock import Mock

        materializer = load(
            "dsm928_privileged_materializer",
            ROOT / "agents/linux/privileged/materialize_instance.py")
        native = load(
            "dsm928_privileged_native_command",
            ROOT / "agents/linux/privileged/native_command.py")
        helpers = ((materializer, "dayz-002"), (native, "native-command-123"))

        # Both real run() entrypoints must check a genuine current hold before
        # touching any request file, runtime, instance or game.
        for observed in (
            {"active": True, "reason": "root_owned_maintenance_hold"},
            {"active": True, "reason": "pending_journal_requires_operator_recovery"},
            {"active": "invalid"},
            None,
        ):
            with self.subTest(observed=observed), \
                 patch.object(admission, "observe", return_value=observed):
                for helper, ident in helpers:
                    with patch.object(helper.os, "geteuid", return_value=0), \
                         patch.object(Path, "read_text",
                                      side_effect=AssertionError("request read before hold check")):
                        with self.assertRaisesRegex(
                                admission.PrivilegedMutationHold,
                                "agent_privileged_maintenance_hold_active"):
                            helper.run(ident)

        # Reader exceptions also fail closed, not fallback to 'no hold'.
        with patch.object(admission, "observe", side_effect=OSError("missing evidence")):
            with self.assertRaises(admission.PrivilegedMutationHold):
                admission.require_privileged_mutation_admission()

        # Explicitly absent hold must allow old routing to proceed to the
        # request-file read; we deliberately abort before any real action.
        with patch.object(admission, "observe", return_value={"active": False}):
            for helper, ident in helpers:
                with patch.object(helper.os, "geteuid", return_value=0), \
                     patch.object(Path, "read_text", side_effect=LookupError("fixture stop")):
                    with self.assertRaisesRegex(LookupError, "fixture stop"):
                        helper.run(ident)

        # Materializer's legacy apply-error cleanup grants read access.
        # It must never run this mutation if the *reason* for error is a
        # maintenance hold. The error result itself is allowed bookkeeping.
        with tempfile.TemporaryDirectory(prefix="dsm928-privileged-") as temp:
            root = Path(temp)
            (root / "dayz-002.request.json").write_text(
                json.dumps({"action": "apply"}), encoding="utf-8")
            with patch.object(materializer, "REQUEST_ROOT", root), \
                 patch.object(materializer.sys, "argv",
                              ["materialize_instance.py", "dayz-002"]), \
                 patch.object(admission, "observe",
                              return_value={"active": True}), \
                 patch.object(materializer.os, "geteuid", return_value=0), \
                 patch.object(materializer, "_grant_customer_files_access") as grant:
                self.assertEqual(materializer.main(), 1)
                grant.assert_not_called()
            result = json.loads(
                (root / "dayz-002.result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertIn("maintenance_hold_active", result["error"])


    def test_root_helpers_share_real_cross_process_inflight_lock(self):
        """Grouped #928 proof: 2 real helper functions and a second Python PID.

        All paths live under a temporary directory. No actual systemd units,
        game commands, ACL changes, or privileged host writes are executed.
        """
        import os
        import stat
        import subprocess
        import threading
        from unittest.mock import Mock
        import game_uptime_privileged_flock as witness

        uid = os.geteuid()
        with tempfile.TemporaryDirectory(prefix="dsm928-helper-flock-") as temp:
            root = Path(temp)
            folder = root / "fixed-locks"
            folder.mkdir(mode=0o755)
            lock_path = folder / "agent-privileged-operations.lock"

            witness.provision_privileged_helper_lock(
                path=lock_path, trusted_uid=uid)
            inode = lock_path.stat().st_ino
            witness.provision_privileged_helper_lock(
                path=lock_path, trusted_uid=uid)
            self.assertEqual(lock_path.stat().st_ino, inode)
            self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

            # No opt-in must preserve installed old semantics.
            with witness.shared_privileged_helper_lock(
                    path=lock_path, trusted_uid=uid, enabled=False) as active:
                self.assertFalse(active)

            def shared():
                return witness.shared_privileged_helper_lock(
                    path=lock_path, trusted_uid=uid, enabled=True)

            def exclusive():
                return witness.exclusive_privileged_helper_lock(
                    path=lock_path, trusted_uid=uid)

            probe = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from game_uptime_privileged_flock import (
    exclusive_privileged_helper_lock, PrivilegedHelperFenceUnavailable,
)
try:
    with exclusive_privileged_helper_lock(
            path=Path(sys.argv[1]), trusted_uid=int(sys.argv[3])) as result:
        print("EXCLUSIVE:" + str(result["live_no_drain_authorized"]))
except PrivilegedHelperFenceUnavailable:
    print("BUSY")
"""

            def child_exclusive():
                done = subprocess.run(
                    [sys.executable, "-c", probe, str(lock_path),
                     str(ROOT / "agents/linux/runtime"), str(uid)],
                    capture_output=True, check=True, text=True, timeout=12)
                return done.stdout.strip()

            self.assertEqual(child_exclusive(), "EXCLUSIVE:False")

            materializer = load(
                "dsm928_materialize_inflight",
                ROOT / "agents/linux/privileged/materialize_instance.py")
            native = load(
                "dsm928_native_inflight",
                ROOT / "agents/linux/privileged/native_command.py")

            for helper, ident in (
                (materializer, "dayz-002"),
                (native, "native-command-123"),
            ):
                with self.subTest(helper=helper.__name__):
                    self.assertTrue(hasattr(helper.run, "__wrapped__"))
                    entered = threading.Event()
                    release = threading.Event()
                    errors = []

                    def pause_request_read(*_args, **_kwargs):
                        entered.set()
                        if not release.wait(timeout=12):
                            raise AssertionError("helper witness timeout")
                        raise LookupError("synthetic pre-mutation stop")

                    def worker():
                        try:
                            helper.run(ident)
                        except BaseException as exc:
                            errors.append(exc)

                    with patch.object(
                            admission, "shared_privileged_helper_lock",
                            side_effect=shared), patch.object(
                            admission, "observe",
                            return_value={"active": False}), patch.object(
                            helper.os, "geteuid", return_value=0), patch.object(
                            Path, "read_text", side_effect=pause_request_read):
                        thread = threading.Thread(
                            target=worker, daemon=True)
                        try:
                            thread.start()
                            self.assertTrue(entered.wait(timeout=12))
                            self.assertEqual(child_exclusive(), "BUSY")
                        finally:
                            release.set()
                            thread.join(timeout=12)
                        self.assertFalse(thread.is_alive())
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], LookupError)
                    self.assertEqual(child_exclusive(), "EXCLUSIVE:False")

            # A coordinator holding EX denies *both* new helpers before
            # either reads a request, even if the hold marker is absent.
            with patch.object(
                    admission, "shared_privileged_helper_lock",
                    side_effect=shared), patch.object(
                    admission, "observe",
                    return_value={"active": False}), patch.object(
                    Path, "read_text",
                    side_effect=AssertionError("request must not be read")):
                with exclusive() as negative:
                    self.assertFalse(negative["privileged_helper_acked"])
                    self.assertFalse(negative["live_no_drain_authorized"])
                    for helper, ident in (
                        (materializer, "dayz-002"),
                        (native, "native-command-123"),
                    ):
                        with patch.object(helper.os, "geteuid", return_value=0):
                            with self.assertRaisesRegex(
                                    admission.PrivilegedMutationHold,
                                    "agent_privileged_inflight_fence_unavailable"):
                                helper.run(ident)

            # Recovery ACL path must not bypass EX even after a failed run.
            with patch.object(
                    admission, "shared_privileged_helper_lock",
                    side_effect=shared), patch.object(
                    materializer.os, "geteuid", return_value=0), patch.object(
                    materializer.sys, "argv",
                    ["materialize_instance.py", "dayz-002"]), patch.object(
                    Path, "read_text",
                    side_effect=AssertionError("forbidden recovery read")), patch.object(
                    materializer, "_grant_customer_files_access") as grant, patch.object(
                    materializer, "_write_result") as write_result:
                with exclusive():
                    self.assertEqual(materializer.main(), 1)
                grant.assert_not_called()
                self.assertEqual(write_result.call_args.args[1]["status"], "failed")

            # No accidental recovery from missing/unsafe inode under opt-in.
            lock_path.chmod(0o666)
            try:
                with self.assertRaises(
                        witness.PrivilegedHelperFenceUnavailable):
                    with shared():
                        self.fail("unsafe existing inode must be refused")
            finally:
                lock_path.chmod(0o600)
            self.assertEqual(child_exclusive(), "EXCLUSIVE:False")


if __name__ == "__main__":
    unittest.main()
