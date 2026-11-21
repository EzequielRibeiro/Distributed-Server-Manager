"""#928: isolated execution of the actual Agent run_forever scheduler.

This is NOT a full Controller daemon, a real Agent host inventory, or a
no-drain update. All host-mutating startup hooks are replaced with fail-closed
guards; the loop and its error/retry behavior are real.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import json
import os
import tempfile
import time
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
import agent as linux_agent
from game_uptime_maintenance_hold import observe as observe_maintenance_hold


class StopFixture(Exception):
    pass


class AgentRunForeverLoopTests(unittest.TestCase):
    def test_each_worker_loop_checks_maintenance_hold_before_mutation(self):
        """One grouped regression guard for existing Worker loop entrypoints.

        This tests guard placement, not a drained/acknowledged in-flight task
        or actual runtime safety across a multi-host release.
        """
        import ast
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader

        workers = ROOT / "dashboard" / "workers"
        spec = spec_from_loader(
            "dsm928_maintenance_hold_gate",
            SourceFileLoader("dsm928_maintenance_hold_gate",
                             str(workers / "maintenance_hold_gate.py")),
        )
        gate = module_from_spec(spec)
        spec.loader.exec_module(gate)
        with patch.object(gate, "observe", return_value={"active": True}):
            self.assertTrue(gate.maintenance_paused())
        with patch.object(gate, "observe", return_value={"active": False}):
            self.assertFalse(gate.maintenance_paused())

        names = (
            "automation_worker.py",
            "content_update_worker.py",
            "maintenance_worker.py",
            "observability_retention_worker.py",
            "content_upload_retention_worker.py",
            "database_intelligence_worker.py",
            "hybrid_customer_workspace_worker.py",
        )
        def is_guard(value):
            return (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "maintenance_paused")

        for filename in names:
            with self.subTest(worker=filename):
                source = (workers / filename).read_text(encoding="utf-8")
                tree = ast.parse(source)
                loop = next(
                    node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "run_forever"
                )
                first = loop.body[0]
                self.assertIsInstance(first, ast.While)
                self.assertTrue(is_guard(first.test))
                perpetual = next(
                    node for node in loop.body if isinstance(node, ast.While)
                    and isinstance(node.test, ast.Constant)
                    and node.test.value is True
                )
                self.assertIsInstance(perpetual.body[0], ast.If)
                self.assertTrue(is_guard(perpetual.body[0].test))
                self.assertIn("from maintenance_hold_gate import maintenance_paused",
                              source)
        script = (workers / "scheduler_worker.sh").read_text(encoding="utf-8")
        self.assertIn('python3 -B "${HOLD_GATE}" --scheduler-tick', script)
        self.assertIn("scheduler_update", script)
        self.assertIn('if [[ "${1:-}" == "--once" ]]', script)
        workspace = ast.parse((workers / "hybrid_customer_workspace_worker.py")
                              .read_text(encoding="utf-8"))
        cycle = next(node for node in workspace.body
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "workspace_cycle")
        lock_context = next((node for node in cycle.body
                             if isinstance(node, ast.With)), None)
        self.assertIsNotNone(lock_context)
        self.assertIn("tracked_operation",
                      ast.unparse(lock_context.items[0].context_expr))
        guarded_cycle = next(node for node in workspace.body
                             if isinstance(node, ast.FunctionDef)
                             and node.name == "_workspace_cycle")
        self.assertIsInstance(guarded_cycle.body[0], ast.If)
        self.assertTrue(is_guard(guarded_cycle.body[0].test))

    def test_all_nine_worker_inflight_locks_are_observable_without_authorization(self):
        """One grouped contract: busy evidence for all nine, never live ACK."""
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader

        filename = ROOT / "dashboard" / "workers" / "maintenance_hold_gate.py"
        spec = spec_from_loader("dsm928_inflight_lock", SourceFileLoader(
            "dsm928_inflight_lock", str(filename)))
        gate = module_from_spec(spec)
        spec.loader.exec_module(gate)
        names = {
            "scheduler_worker",
            "automation_worker",
            "content_update_worker",
            "maintenance_worker",
            "observability_retention_worker",
            "content_upload_retention_worker",
            "database_intelligence_worker",
            "hybrid_agent_worker",
            "hybrid_customer_workspace_worker",
        }
        self.assertEqual(set(gate._KNOWN_WORKERS), names)
        workers = ROOT / "dashboard" / "workers"
        for name in sorted(names - {"scheduler_worker"}):
            source = (workers / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn(f'with tracked_operation("{name}"', source, name)
        scheduler = (workers / "scheduler_worker.sh").read_text(encoding="utf-8")
        self.assertIn('--scheduler-tick', scheduler)
        self.assertIn('tracked_operation("scheduler_worker"', filename.read_text())
        # The installed lock location is independent of replaceable DSM
        # code. Provisioning lives in a root-only systemd ExecStartPre.
        self.assertEqual(str(gate.LOCK_DIRECTORY),
                         "/run/capivara-dsm/worker-operations")
        unit = (ROOT / "systemd/dsm-dashboard-worker.service").read_text()
        self.assertIn("prepare_maintenance_worker_locks.py", unit)
        initializer_path = workers / "prepare_maintenance_worker_locks.py"
        init_spec = spec_from_loader(
            "dsm928_lock_initializer",
            SourceFileLoader("dsm928_lock_initializer", str(initializer_path)),
        )
        initializer = module_from_spec(init_spec)
        with patch.dict(sys.modules, {"maintenance_hold_gate": gate}):
            init_spec.loader.exec_module(initializer)

        with tempfile.TemporaryDirectory(prefix="dsm928-inflight-") as temp:
            root = Path(temp)
            lock_dir = root / "protected" / "worker-operations"
            first = gate.inspect_operation(
                "maintenance_worker", root=root, lock_dir=lock_dir)
            self.assertEqual(first["status"], "unverified")
            with self.assertRaises((OSError, RuntimeError)):
                with gate.tracked_operation(
                        "maintenance_worker", root=root, lock_dir=lock_dir):
                    self.fail("no operation without pre-provisioned lock")

            initializer.prepare(
                os.geteuid(), os.getegid(),
                directory=lock_dir, parent_owner=os.geteuid())
            original_inodes = {
                name: (lock_dir / (name + ".lock")).stat().st_ino
                for name in names
            }
            # Re-running ExecStartPre must not remove, recreate, or change
            # existing inodes: flock identity must survive service restarts.
            initializer.prepare(
                os.geteuid(), os.getegid(),
                directory=lock_dir, parent_owner=os.geteuid())
            self.assertEqual(original_inodes, {
                name: (lock_dir / (name + ".lock")).stat().st_ino
                for name in names
            })

            for name in sorted(names):
                with self.subTest(worker=name):
                    with patch.object(gate, "maintenance_paused",
                                      return_value=False):
                        with gate.tracked_operation(
                                name, root=root, lock_dir=lock_dir) as admitted:
                            self.assertTrue(admitted)
                            busy = gate.inspect_operation(
                                name, root=root, lock_dir=lock_dir)
                            self.assertEqual(busy["status"],
                                             "operation_in_flight")
                            self.assertFalse(busy["live_no_drain_authorized"])
                    free = gate.inspect_operation(
                        name, root=root, lock_dir=lock_dir)
                    self.assertEqual(free["status"],
                                     "lock_free_process_identity_unverified")
                    self.assertFalse(free["live_no_drain_authorized"])

            with patch.object(gate, "maintenance_paused", return_value=True):
                with gate.tracked_operation(
                        "maintenance_worker", root=root,
                        lock_dir=lock_dir) as admitted:
                    self.assertFalse(admitted)
            with self.assertRaises(ValueError):
                with gate.tracked_operation(
                        "../untrusted", root=root, lock_dir=lock_dir):
                    pass

            # A forged symlink must never become a valid lock witness.
            victim = lock_dir / "scheduler_worker.lock"
            victim.rename(lock_dir / "scheduler_worker.saved")
            victim.symlink_to(lock_dir / "scheduler_worker.saved")
            self.assertEqual(gate.inspect_operation(
                "scheduler_worker", root=root, lock_dir=lock_dir)["status"],
                "unverified")
            with self.assertRaises((OSError, RuntimeError)):
                initializer.prepare(
                    os.geteuid(), os.getegid(),
                    directory=lock_dir, parent_owner=os.geteuid())

    def test_readonly_worker_identity_diagnostic_fails_closed_on_pid_reuse(self):
        """One grouped Linux /proc + systemd identity regression for #928."""
        import io
        import pwd
        from contextlib import redirect_stdout
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader

        workers = ROOT / "dashboard/workers"
        module_path = workers / "worker_identity_diagnostic.py"
        gate_path = workers / "maintenance_hold_gate.py"
        gate_spec = spec_from_loader("dsm928_diag_gate",
                                     SourceFileLoader("dsm928_diag_gate",
                                                      str(gate_path)))
        gate = module_from_spec(gate_spec)
        gate_spec.loader.exec_module(gate)
        diag_spec = spec_from_loader("dsm928_worker_identity",
                                     SourceFileLoader("dsm928_worker_identity",
                                                      str(module_path)))
        diag = module_from_spec(diag_spec)
        with patch.dict(sys.modules, {"maintenance_hold_gate": gate}):
            diag_spec.loader.exec_module(diag)

        uid = os.geteuid()
        username = pwd.getpwuid(uid).pw_name
        group = "/system.slice/dsm-dashboard-worker.service"
        root = Path("/opt/dsm")
        names = sorted(gate._KNOWN_WORKERS)
        first_pid = 9100
        main_pid = 9000
        unit = {"ActiveState": "active", "SubState": "running",
                "MainPID": str(main_pid), "User": username,
                "ControlGroup": group}

        def make_stat(pid, ppid, ticks):
            # Linux /proc/PID/stat fields 3=state, 4=PPID, 22=starttime.
            return (f"{pid} (synthetic worker) S {ppid} "
                    + "0 " * 17 + f"{ticks} 0\n")

        def write_proc(proc_root, pid, ppid, ticks, script, program):
            home = proc_root / str(pid)
            home.mkdir(parents=True, exist_ok=True)
            (home / "stat").write_text(make_stat(pid, ppid, ticks))
            (home / "status").write_text(
                f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
            (home / "cgroup").write_text("0::" + group + "\n")
            (home / "cmdline").write_bytes(
                (program + "\0" + script + "\0").encode("utf-8"))

        with tempfile.TemporaryDirectory(prefix="dsm928-worker-ids-") as tmp:
            proc_root = Path(tmp) / "proc"
            parent_script = str(root / "dashboard/workers/worker.sh")
            write_proc(proc_root, main_pid, 1, 100,
                       parent_script, "/bin/bash")
            children = []
            for index, name in enumerate(names):
                pid = first_pid + index
                children.append(pid)
                script = (name + ".py" if name != "scheduler_worker"
                          else "scheduler_worker.sh")
                program = "python3" if name != "scheduler_worker" else "bash"
                write_proc(proc_root, pid, main_pid, 200 + index,
                           str(root / "dashboard/workers" / script), program)
            proc_task = proc_root / str(main_pid) / "task" / str(main_pid)
            proc_task.mkdir(parents=True)
            (proc_task / "children").write_text(
                " ".join(str(pid) for pid in children) + "\n")

            snapshot = diag._snapshot(main_pid, proc_root)
            locks = {name: "lock_free_process_identity_unverified"
                     for name in names}
            good = diag.evaluate(unit, snapshot, locks, expected_uid=uid)
            self.assertEqual(good["status"], "local_identity_verified_only")
            self.assertTrue(good["workers_verified"])
            self.assertTrue(good["locks_free_candidate"])
            self.assertEqual(len(good["workers"]), 9)
            self.assertFalse(good["live_no_drain_authorized"])

            busy = dict(locks)
            busy["maintenance_worker"] = "operation_in_flight"
            self.assertFalse(
                diag.evaluate(unit, snapshot, busy, expected_uid=uid)[
                    "locks_free_candidate"])
            missing = dict(snapshot)
            missing["children"] = snapshot["children"][:-1]
            self.assertFalse(
                diag.evaluate(unit, missing, locks, expected_uid=uid)[
                    "workers_verified"])
            altered = dict(snapshot)
            altered["children"] = [
                {**item, "ppid": 1} if item["pid"] == first_pid else item
                for item in snapshot["children"]
            ]
            self.assertFalse(
                diag.evaluate(unit, altered, locks, expected_uid=uid)[
                    "workers_verified"])
            self.assertFalse(
                diag.evaluate(unit, snapshot, locks, expected_uid=uid,
                              stable=False)["workers_verified"])

            def lock_info(name, **_kwargs):
                return {"worker": name, "status": locks[name],
                        "live_no_drain_authorized": False}

            with patch.object(diag, "_unit_status", return_value=unit), \
                 patch.object(diag, "inspect_operation",
                              side_effect=lock_info):
                observed = diag.inspect(proc_root=proc_root)
                self.assertEqual(observed["status"],
                                 "local_identity_verified_only")
                self.assertFalse(observed["live_no_drain_authorized"])
                output = io.StringIO()
                with patch.object(diag, "inspect", return_value=observed), \
                     redirect_stdout(output):
                    self.assertEqual(diag.main(["--inspect"]), 2)
                self.assertFalse(json.loads(output.getvalue())[
                    "live_no_drain_authorized"])

            # Simulate PID reuse between the two procfs observations.
            changed = diag._snapshot(main_pid, proc_root)
            changed["children"][0] = {
                **changed["children"][0], "start_ticks": 99000}
            with patch.object(diag, "_unit_status", return_value=unit), \
                 patch.object(diag, "_snapshot",
                              side_effect=[snapshot, changed]), \
                 patch.object(diag, "inspect_operation",
                              side_effect=lock_info):
                reused = diag.inspect(proc_root=proc_root)
                self.assertEqual(reused["status"], "unverified")
                self.assertIn("identity_changed_during_observation",
                              reused["errors"])
                self.assertFalse(reused["live_no_drain_authorized"])

    def test_local_transaction_fence_holds_all_nine_locks_fail_closed(self):
        """One grouped stage-2 contract; never authorizes a live updater."""
        import fcntl
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader

        workers = ROOT / "dashboard/workers"
        with patch.object(sys, "path", [str(workers), *sys.path]):
            # Runtime entrypoints import these sibling modules normally.
            import local_worker_fence as fence
            import maintenance_hold_gate as gate
            import prepare_maintenance_worker_locks as initializer

        valid = {
            "active": True, "reason": "root_owned_maintenance_hold",
            "transaction_id": "a" * 32,
            "issued_at": 100, "expires_at": 200,
        }
        names = tuple(sorted(gate._KNOWN_WORKERS))
        identity = {
            "status": "local_identity_verified_only",
            "supervisor_verified": True, "workers_verified": True,
            "workers": {name: {"pid": 1000 + index}
                        for index, name in enumerate(names)},
            "live_no_drain_authorized": False,
        }
        with tempfile.TemporaryDirectory(prefix="dsm928-stage2-fence-") as tmp:
            root = Path(tmp)
            folder = root / "root-owned" / "locks"
            initializer.prepare(
                os.geteuid(), os.getegid(),
                directory=folder, parent_owner=os.geteuid())
            opts = {"root": root, "lock_dir": folder}
            with patch.object(fence, "observe", return_value=valid), \
                 patch.object(fence, "inspect_worker_identity",
                              return_value=identity):
                with fence.local_worker_fence(**opts) as state:
                    self.assertEqual(state["status"],
                                     "tracked_local_worker_cycles_fenced")
                    self.assertEqual(state["worker_count"], 9)
                    self.assertEqual(state["transaction_id"], "a" * 32)
                    self.assertFalse(state["remote_agents_acked"])
                    self.assertFalse(state["external_jobs_acked"])
                    self.assertFalse(state["live_no_drain_authorized"])
                    for name in names:
                        with self.subTest(worker=name):
                            evidence = gate.inspect_operation(
                                name, root=root, lock_dir=folder)
                            self.assertEqual(evidence["status"],
                                             "operation_in_flight")
                    # Concurrent local coordinator must fail (no wait/retry).
                    with self.assertRaises(fence.LocalFenceUnavailable):
                        with fence.local_worker_fence(**opts):
                            self.fail("must never enter a second fence")

                for name in names:
                    free = gate.inspect_operation(name, root=root, lock_dir=folder)
                    self.assertEqual(free["status"],
                                     "lock_free_process_identity_unverified")

                denied = {"active": False, "reason": "hold_absent"}
                with patch.object(fence, "observe", return_value=denied):
                    with self.assertRaises(fence.LocalFenceUnavailable):
                        with fence.local_worker_fence(**opts):
                            self.fail("hold is mandatory")
                with patch.object(fence, "inspect_worker_identity",
                                  return_value={"status": "unverified"}):
                    with self.assertRaises(fence.LocalFenceUnavailable):
                        with fence.local_worker_fence(**opts):
                            self.fail("process identity required")
                changed = {**valid, "transaction_id": "b" * 32}
                with patch.object(fence, "observe",
                                  side_effect=[valid, changed]):
                    with self.assertRaises(fence.LocalFenceUnavailable):
                        with fence.local_worker_fence(**opts):
                            self.fail("transaction ID switched")
                # Even after failure in the middle, no preceding lock leaks.
                last = folder / (names[-1] + ".lock")
                fd = os.open(last, os.O_RDWR)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(fence.LocalFenceUnavailable):
                        with fence.local_worker_fence(**opts):
                            self.fail("busy Worker must block local fence")
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                for name in names:
                    self.assertEqual(gate.inspect_operation(
                        name, root=root, lock_dir=folder)["status"],
                        "lock_free_process_identity_unverified")

    def test_root_owned_maintenance_hold_fail_closed_and_no_agent_startup(self):
        with tempfile.TemporaryDirectory(prefix="dsm928-protected-hold-") as temp:
            folder = Path(temp) / "protected"
            folder.mkdir(mode=0o700)
            marker = folder / "maintenance.json"
            now = int(time.time())
            arguments = {"path": marker, "trusted_uid": os.geteuid(), "now": now}
            self.assertFalse(observe_maintenance_hold(**arguments)["active"])
            payload = {
                "kind": "CapivaraDSMNoDrainMaintenanceHold",
                "schema_version": 1,
                "transaction_id": "a" * 32,
                "issued_at": now - 10,
                "expires_at": now + 300,
            }
            marker.write_text(json.dumps(payload))
            marker.chmod(0o644)
            self.assertEqual(observe_maintenance_hold(**arguments)["reason"],
                             "root_owned_maintenance_hold")
            self.assertEqual(
                observe_maintenance_hold(path=marker, trusted_uid=os.geteuid(),
                                         now=now + 301)["reason"],
                "hold_expired_requires_operator")
            marker.write_text("damaged")
            self.assertTrue(observe_maintenance_hold(**arguments)["active"])
            marker.chmod(0o666)
            self.assertEqual(observe_maintenance_hold(**arguments)["reason"],
                             "hold_file_untrusted")

        # An active hold must stop the Agent BEFORE enrollment, recovery and
        # any first reconciliation/heartbeat. No synthetic game mutations.
        with patch.object(linux_agent, "observe_no_drain_hold",
                          return_value={"active": True, "reason": "maintenance"}), \
             patch.object(linux_agent, "_load_config",
                          side_effect=AssertionError("Agent startup executed")), \
             patch.object(linux_agent.time, "sleep", side_effect=StopFixture):
            with self.assertRaises(StopFixture):
                linux_agent.run_forever()

    def test_scheduler_recovers_after_heartbeat_failure_without_host_operations(self):
        config = {
            "agent_id": "dsm928-fixture-agent",
            "credential_id": "fixture-id",
            "credential_secret": "fixture-secret",
            "heartbeat_interval_seconds": 10,
            "reconcile_interval_seconds": 5,
        }
        calls = []
        clock = [100.0]
        heartbeat_attempts = [0]

        def forbidden(*_args, **_kwargs):
            raise AssertionError("unexpected host operation in #928 fixture")

        def heartbeat(_config):
            heartbeat_attempts[0] += 1
            calls.append("heartbeat")
            if heartbeat_attempts[0] == 1:
                raise ConnectionError("disposable Controller temporarily unavailable")
            return {"agent_id": config["agent_id"], "health_status": "online", "status": "active"}

        def reconcile(_config):
            calls.append("reconcile")

        def sleep(_seconds):
            clock[0] += 11.0
            if heartbeat_attempts[0] >= 2:
                raise StopFixture()

        with ExitStack() as stack:
            stack.enter_context(patch.object(linux_agent, "_load_config", return_value=config))
            stack.enter_context(patch.object(linux_agent, "enroll", side_effect=forbidden))
            stack.enter_context(patch.object(linux_agent, "recover_interrupted_operations", return_value=[]))
            stack.enter_context(patch.object(linux_agent, "start_console_stream", return_value=None))
            stack.enter_context(patch.object(linux_agent, "start_content_update_inventory", return_value=None))
            stack.enter_context(patch.object(linux_agent, "FinalizationWorkerSupervisor", return_value=object()))
            stack.enter_context(patch.object(linux_agent, "reconcile_all", side_effect=reconcile))
            stack.enter_context(patch.object(linux_agent, "heartbeat", side_effect=heartbeat))
            stack.enter_context(patch.object(linux_agent.time, "monotonic", side_effect=lambda: clock[0]))
            stack.enter_context(patch.object(linux_agent.time, "sleep", side_effect=sleep))
            stack.enter_context(patch.object(linux_agent, "_log", return_value=None))
            for name in (
                "CAPIVARA_SERVERPACK_FINALIZATION_AUDIT",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE",
            ):
                stack.enter_context(patch.dict(linux_agent.os.environ, {name: ""}))
            with self.assertRaises(StopFixture):
                linux_agent.run_forever()

        self.assertEqual(heartbeat_attempts[0], 2)
        self.assertEqual(calls, ["reconcile", "heartbeat", "reconcile", "heartbeat"])


if __name__ == "__main__":
    unittest.main()
