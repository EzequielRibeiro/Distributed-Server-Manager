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


    def test_backup_create_restore_and_firewall_join_same_inflight_fence(self):
        """Grouped #928 test: three real run() paths, one inode, second PID.

        External side effects stop before reading requests. No backup restore,
        UFW command, host writes, Agent service or game is invoked.
        """
        import os
        import stat
        import subprocess
        import threading
        from game_uptime_privileged_flock import (
            provision_privileged_helper_lock, shared_privileged_helper_lock,
            exclusive_privileged_helper_lock, PrivilegedHelperFenceUnavailable,
        )

        uid = os.geteuid()
        creator = load(
            "dsm928_backup_create_inflight",
            ROOT / "agents/linux/privileged/create_instance_backup.py")
        restorer = load(
            "dsm928_backup_restore_inflight",
            ROOT / "agents/linux/privileged/restore_instance_backup.py")
        firewall = load(
            "dsm928_firewall_inflight",
            ROOT / "agents/linux/privileged/reconcile_firewall.py")
        candidates = (
            (creator, "backup-928-create"),
            (restorer, "backup-928-restore"),
            (firewall, "dayz-002"),
        )

        with tempfile.TemporaryDirectory(prefix="dsm928-backup-firewall-flock-") as temp:
            folder = Path(temp) / "trusted"
            folder.mkdir(mode=0o755)
            lock = folder / "agent-privileged-operations.lock"
            provision_privileged_helper_lock(path=lock, trusted_uid=uid)
            self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

            def shared():
                return shared_privileged_helper_lock(
                    path=lock, trusted_uid=uid, enabled=True)

            def exclusive():
                return exclusive_privileged_helper_lock(
                    path=lock, trusted_uid=uid)

            probe = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from game_uptime_privileged_flock import (
    exclusive_privileged_helper_lock, PrivilegedHelperFenceUnavailable,
)
try:
    with exclusive_privileged_helper_lock(
            path=Path(sys.argv[1]), trusted_uid=int(sys.argv[3])) as evidence:
        print("EX:" + str(evidence["live_no_drain_authorized"]))
except PrivilegedHelperFenceUnavailable:
    print("BUSY")
"""

            def child_probe():
                done = subprocess.run([
                    sys.executable, "-c", probe, str(lock),
                    str(ROOT / "agents/linux/runtime"), str(uid),
                ], capture_output=True, check=True, text=True, timeout=12)
                return done.stdout.strip()

            self.assertEqual(child_probe(), "EX:False")

            # Root hold must be consulted before any request or UFW action.
            with patch.object(admission, "observe", return_value={"active": True}), \
                 patch.object(admission, "shared_privileged_helper_lock",
                              side_effect=shared), \
                 patch.object(Path, "read_text",
                              side_effect=AssertionError("request read under hold")), \
                 patch.object(firewall, "_atomic_json") as save:
                for helper, ident in candidates:
                    with self.subTest(hold=helper.__name__):
                        with patch.object(helper.os, "geteuid", return_value=0):
                            if helper is firewall:
                                response = helper.run(ident)
                                self.assertEqual(response["status"], "failed")
                                self.assertIn("maintenance_hold_active", response["error"])
                            else:
                                with self.assertRaises(admission.PrivilegedMutationHold):
                                    helper.run(ident)
                self.assertEqual(save.call_count, 1)

            # While each of the three parent processes is still in run(),
            # a separate PID cannot obtain the coordinator's exclusive EX.
            for helper, ident in candidates:
                with self.subTest(in_flight=helper.__name__):
                    ready = threading.Event()
                    release = threading.Event()
                    errors, responses = [], []

                    def pending_read(*_args, **_kwargs):
                        ready.set()
                        if not release.wait(timeout=12):
                            raise AssertionError("helper in-flight fixture timeout")
                        raise LookupError("fixture read stopped")

                    def operate():
                        try:
                            responses.append(helper.run(ident))
                        except BaseException as exc:
                            errors.append(exc)

                    with patch.object(admission, "observe",
                                      return_value={"active": False}), \
                         patch.object(admission, "shared_privileged_helper_lock",
                                      side_effect=shared), \
                         patch.object(helper.os, "geteuid", return_value=0), \
                         patch.object(Path, "read_text",
                                      side_effect=pending_read), \
                         patch.object(firewall, "_atomic_json"):
                        worker = threading.Thread(target=operate, daemon=True)
                        try:
                            worker.start()
                            self.assertTrue(ready.wait(timeout=12))
                            self.assertEqual(child_probe(), "BUSY")
                        finally:
                            release.set()
                            worker.join(timeout=12)
                        self.assertFalse(worker.is_alive())
                    if helper is firewall:
                        self.assertEqual(errors, [])
                        self.assertEqual(responses[0]["status"], "failed")
                    else:
                        self.assertEqual(len(errors), 1)
                        self.assertIsInstance(errors[0], LookupError)
                    self.assertEqual(child_probe(), "EX:False")

            # A coordinator already holding EX must reject all three
            # entrypoints *before* reading a request.
            with patch.object(admission, "shared_privileged_helper_lock",
                              side_effect=shared), \
                 patch.object(admission, "observe",
                              return_value={"active": False}), \
                 patch.object(Path, "read_text",
                              side_effect=AssertionError("bypassed EX")), \
                 patch.object(firewall, "_atomic_json") as save:
                with exclusive() as proof:
                    self.assertFalse(proof["live_no_drain_authorized"])
                    self.assertFalse(proof["privileged_helper_acked"])
                    self.assertIn("five_", proof["scope"])
                    for helper, ident in candidates:
                        with patch.object(helper.os, "geteuid", return_value=0):
                            with self.assertRaisesRegex(
                                    admission.PrivilegedMutationHold,
                                    "agent_privileged_inflight_fence_unavailable"):
                                helper.run(ident)
                save.assert_not_called()

            # Invalid inode can never be treated as an idle helper.
            lock.chmod(0o666)
            try:
                with self.assertRaises(PrivilegedHelperFenceUnavailable):
                    with shared():
                        self.fail("unsafe witness must be rejected")
            finally:
                lock.chmod(0o600)


    def test_customer_files_and_identity_share_privileged_fence(self):
        """One grouped proof: admission, in-flight EX and no host mutation.

        Only synthetic pre-mutation stops are used; no usermod, chmod,
        instance writes or Agent service is invoked.
        """
        import os
        import subprocess
        import threading
        from game_uptime_privileged_flock import (
            provision_privileged_helper_lock,
            shared_privileged_helper_lock,
            exclusive_privileged_helper_lock,
        )

        customer = load(
            "dsm928_customer_files_fence",
            ROOT / "agents/linux/privileged/prepare_customer_files.py")
        identity = load(
            "dsm928_runtime_identity_fence",
            ROOT / "agents/linux/privileged/reconcile_runtime_identity.py")
        self.assertTrue(hasattr(customer.run, "__wrapped__"))
        self.assertTrue(hasattr(identity.reconcile, "__wrapped__"))

        with tempfile.TemporaryDirectory(prefix="dsm928-identity-files-") as temp:
            folder = Path(temp) / "trusted"
            folder.mkdir(mode=0o755)
            lock = folder / "agent-privileged-operations.lock"
            uid = os.geteuid()
            provision_privileged_helper_lock(path=lock, trusted_uid=uid)

            def shared():
                return shared_privileged_helper_lock(
                    path=lock, trusted_uid=uid, enabled=True)

            def exclusive():
                return exclusive_privileged_helper_lock(
                    path=lock, trusted_uid=uid)

            # All operations must fail before accessing the request or
            # changing host identities while a maintenance hold is active.
            with patch.object(admission, "shared_privileged_helper_lock",
                              side_effect=shared), \
                 patch.object(admission, "observe",
                              return_value={"active": True}), \
                 patch.object(os, "geteuid", return_value=0), \
                 patch.object(Path, "read_text",
                              side_effect=AssertionError("request read under hold")), \
                 patch.object(identity.grp, "getgrnam",
                              side_effect=AssertionError("group lookup under hold")):
                with self.assertRaises(admission.PrivilegedMutationHold):
                    customer.run("dayz-002")
                with self.assertRaises(admission.PrivilegedMutationHold):
                    identity.reconcile()

            # Exclusive coordinator ownership rejects both entrypoints,
            # even when the hold marker explicitly reports inactive.
            with patch.object(admission, "shared_privileged_helper_lock",
                              side_effect=shared), \
                 patch.object(admission, "observe",
                              return_value={"active": False}):
                with exclusive() as witness:
                    self.assertFalse(witness["live_no_drain_authorized"])
                    for invoke in (
                        lambda: customer.run("dayz-002"),
                        identity.reconcile,
                    ):
                        with self.assertRaisesRegex(
                                admission.PrivilegedMutationHold,
                                "agent_privileged_inflight_fence_unavailable"):
                            invoke()

            witness_script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from game_uptime_privileged_flock import (
    exclusive_privileged_helper_lock, PrivilegedHelperFenceUnavailable,
)
try:
    with exclusive_privileged_helper_lock(
            path=Path(sys.argv[1]), trusted_uid=int(sys.argv[3])):
        print("FREE")
except PrivilegedHelperFenceUnavailable:
    print("BUSY")
"""

            def remote_exclusive():
                probe = subprocess.run(
                    [sys.executable, "-c", witness_script, str(lock),
                     str(ROOT / "agents/linux/runtime"), str(uid)],
                    capture_output=True, text=True, check=True, timeout=12)
                return probe.stdout.strip()

            self.assertEqual(remote_exclusive(), "FREE")

            # Each real decorated entrypoint retains SH until its
            # pre-mutation fixture is explicitly released, across PIDs.
            for name, invoke, target, method in (
                ("customer_files", lambda: customer.run("dayz-002"),
                 Path, "read_text"),
                ("runtime_identity", identity.reconcile,
                 identity.grp, "getgrnam"),
            ):
                with self.subTest(helper=name):
                    entered = threading.Event()
                    release = threading.Event()
                    errors = []

                    def pause_before_mutation(*_args, **_kwargs):
                        entered.set()
                        if not release.wait(timeout=12):
                            raise AssertionError("in-flight fixture timed out")
                        raise LookupError("synthetic stop before host mutation")

                    def worker():
                        try:
                            invoke()
                        except BaseException as exc:
                            errors.append(exc)

                    with patch.object(admission, "shared_privileged_helper_lock",
                                      side_effect=shared), \
                         patch.object(admission, "observe",
                                      return_value={"active": False}), \
                         patch.object(os, "geteuid", return_value=0), \
                         patch.object(target, method,
                                      side_effect=pause_before_mutation):
                        thread = threading.Thread(target=worker, daemon=True)
                        try:
                            thread.start()
                            self.assertTrue(entered.wait(timeout=12))
                            self.assertEqual(remote_exclusive(), "BUSY")
                        finally:
                            release.set()
                            thread.join(timeout=12)
                        self.assertFalse(thread.is_alive())
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], LookupError)
                    self.assertEqual(remote_exclusive(), "FREE")


if __name__ == "__main__":
    unittest.main()
