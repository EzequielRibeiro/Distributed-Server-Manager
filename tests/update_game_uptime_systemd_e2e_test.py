"""Opt-in live-systemd, disposable-unit rehearsal for #928 (never runs DSM update).

Runs only with CAPIVARA_DSM928_SYSTEMD_E2E=1 and root; creates two uniquely
named NON-Capivara transient sleep units, so the game Agent cannot discover or
reconcile them. Exercises an isolated file transaction plus rollback with the
real systemd MainPID/start stamp invariant on both processes.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("dsm928_uptime_plan", str(ROOT/"update-manager/game-uptime-plan.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
plan = importlib.util.module_from_spec(spec)
loader.exec_module(plan)

tx_loader = SourceFileLoader(
    "dsm928_disposable_transaction",
    str(ROOT/"update-manager/game-uptime-transaction.py"),
)
tx_spec = importlib.util.spec_from_loader(tx_loader.name, tx_loader)
transaction = importlib.util.module_from_spec(tx_spec)
tx_loader.exec_module(transaction)

guard_loader = SourceFileLoader(
    "dsm928_disposable_reverse_dependency_guard",
    str(ROOT / "update-manager/game-uptime-guard.py"),
)
guard_spec = importlib.util.spec_from_loader(guard_loader.name, guard_loader)
guard = importlib.util.module_from_spec(guard_spec)
guard_loader.exec_module(guard)

from update_game_uptime_real_update_functions_test import (
    create_tiny_release_fixture, run_real_update_fns,
)
from update_game_uptime_main_path_test import main_rehearsal


def disposable_systemd_host(installed_storage=Path("/opt/dsm/runtime/hybrid-instance-storage"),
                            unit_output=None):
    """Deny systemd exercises on installed DSM hosts or any with live games."""
    if installed_storage.exists() or not Path("/run/systemd/system").is_dir():
        return False
    if unit_output is None:
        try:
            result = subprocess.run(
                ("systemctl", "list-units", "--type=service", "--state=active",
                 "--all", "--no-legend", "--plain", "capivara-instance-*.service"),
                text=True, capture_output=True, timeout=8, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
        unit_output = result.stdout
    return not bool(unit_output.strip())


class DisposableSystemdHostSafetyTests(unittest.TestCase):
    def test_refuses_installed_dsm_even_when_opted_in(self):
        with tempfile.TemporaryDirectory(prefix="dsm928-test-installed-") as tmp:
            installed=Path(tmp)/"hybrid-instance-storage"
            installed.mkdir()
            self.assertFalse(disposable_systemd_host(installed, unit_output=""))

    def test_refuses_active_game_service(self):
        with tempfile.TemporaryDirectory(prefix="dsm928-test-units-") as tmp:
            self.assertFalse(disposable_systemd_host(
                Path(tmp)/"absent", unit_output="capivara-instance-minecraft-005.service loaded active running"
            ))


class DisposableSystemdNoDrainTest(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CAPIVARA_DSM928_SYSTEMD_E2E") != "1":
            self.skipTest("opt-in required: CAPIVARA_DSM928_SYSTEMD_E2E=1")
        if os.geteuid() != 0 or not shutil.which("systemd-run"):
            self.skipTest("requires root and systemd-run")
        if not disposable_systemd_host():
            self.skipTest("refuse transient systemd test on a DSM or live-game host")
        self.units = []
        self.addCleanup(self._stop_units)
        self.temp = tempfile.TemporaryDirectory(prefix="dsm928-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.prefix = "dsm928-e2e-" + uuid4().hex[:10]

    @staticmethod
    def _run(*args):
        return subprocess.run(args, text=True, capture_output=True, timeout=15, check=True)

    def _start(self, suffix):
        unit = f"{self.prefix}-{suffix}.service"
        self._run("systemd-run", "--unit", unit[:-8], "--collect",
                  "--property=Type=simple", "/usr/bin/sleep", "180")
        self.units.append(unit)
        for _ in range(30):
            state = self._snapshot(unit)
            if state["state"] == "active" and state["pid"] > 1 and state["started"] > 0:
                return state
            time.sleep(0.1)
        self.fail(f"disposable unit did not start: {unit}")

    def _snapshot(self, unit):
        p = self._run("systemctl", "show", unit, "-p", "MainPID",
                      "-p", "ExecMainStartTimestampMonotonic", "-p", "ActiveState")
        values = dict(line.split("=",1) for line in p.stdout.splitlines() if "=" in line)
        return {"unit":unit, "pid":int(values.get("MainPID","0")),
                "started":int(values.get("ExecMainStartTimestampMonotonic","0")),
                "state":values.get("ActiveState")}

    def _stop_units(self):
        for unit in reversed(getattr(self, "units", [])):
            subprocess.run(("systemctl","stop",unit), capture_output=True,
                           text=True, timeout=15, check=False)

    def _assert_unchanged(self, originals):
        for prior in originals:
            self.assertEqual(self._snapshot(prior["unit"]), prior)

    def test_systemd_exposes_every_reverse_dependency_for_fail_closed_preflight(self):
        """Use a disposable transient unit to validate the host's systemd ABI.

        Without this proof, extra reverse links in the read-only guard could
        incorrectly mark otherwise safe game units as 'incomplete evidence'.
        """
        unit = self._start("reverse-dependencies")
        properties = guard.DEPENDENCY_PROPERTIES
        self.assertEqual(len(set(properties)), len(properties))
        observed = self._run("systemctl", "show", unit["unit"],
                             *(f"--property={name}" for name in properties),
                             "--no-pager")
        returned = {line.split("=", 1)[0] for line in observed.stdout.splitlines()
                    if "=" in line}
        self.assertEqual(set(properties), returned)
        self.assertEqual(self._snapshot(unit["unit"]), unit)

    def test_two_systemd_processes_survive_actual_updater_main_and_failure_rollback(self):
        """Call actual update.sh main() with ONLY production-facing hooks stubbed."""
        originals = [self._start("main-alpha"), self._start("main-beta")]
        for mode, outcome_version in (("success", "2.0.999"), ("fail_after_apply", "2.0.998")):
            with self.subTest(mode=mode):
                fixture = self.workspace/("real-main-" + mode)
                create_tiny_release_fixture(fixture)
                (fixture/"installed/version").write_text("2.0.998")
                (fixture/"new-payload/version").write_text("2.0.999")
                result = main_rehearsal(fixture, mode)
                self.assertEqual(result.returncode == 0, mode == "success",
                                 (result.stdout[-500:], result.stderr[-500:]))
                self.assertEqual((fixture/"installed/version").read_text().strip(), outcome_version)
                self.assertEqual((fixture/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
                                 b"saved-world-private-test")
                self.assertEqual((fixture/"installed/data/database.txt").read_text(),"db durable")
                self._assert_unchanged(originals)

    def test_auth_agent_main_rehearsal_and_two_systemd_pids_stay_consistent(self):
        """One isolated #928 cross-contract proof; never authorizes production.

        Exercise actual Linux Agent heartbeat over credentialed HTTP before
        and after a Controller dispatcher restart, the real update.sh main()
        disposable no-drain entry (success and failed apply/rollback), and
        two independent real systemd processes. The main() fixture uses a
        synthetic game inventory: this is NOT a full daemon/update E2E.
        """
        from update_game_uptime_agent_runtime_restart_test import (
            LinuxAgentProcessHeartbeatTests,
        )
        from update_game_uptime_main_path_test import MainPathRehearsalTest

        originals = [self._start("contract-minecraft"),
                     self._start("contract-dayz")]
        agent = LinuxAgentProcessHeartbeatTests(
            "test_real_agent_process_reconnects_to_restarted_controller")
        agent.setUp()
        self.addCleanup(agent.doCleanups)

        def heartbeat():
            result = agent.invoke()
            self.assertEqual(result.returncode, 0, result.stderr[-1400:])
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(payload["wire_compatible"])
            self.assertFalse(payload["live_no_drain_authorized"])
            self.assertEqual(payload["health_status"], "online")
            self.assertEqual(payload["agent_id"], agent.controller.agent_id)
            return payload

        first = heartbeat()
        self._assert_unchanged(originals)
        for mode, target_version, journal_status in (
            ("no_drain_success", "2.0.999-fixture", "verified"),
            ("no_drain_fail_after_apply", "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(mode=mode):
                main = MainPathRehearsalTest(
                    "test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains")
                main.setUp()
                self.addCleanup(main.doCleanups)
                main.prepare_no_drain_fixture()
                result = main_rehearsal(main.root, mode)
                self.assertEqual(
                    result.returncode, 0 if mode == "no_drain_success" else 2,
                    result.stdout[-1200:] + result.stderr[-1200:])
                self.assertEqual(
                    (main.installed / "version").read_text().strip(),
                    target_version)
                self.assertEqual(main.world.read_bytes(), b"saved-world-private-test")
                self.assertEqual(main.upload.read_bytes(),
                                 b"in-flight-upload-private-test")
                self.assertFalse((main.root / "steps").exists(),
                                 "real game/Controller stop hooks must not run")
                receipt = json.loads((
                    main.root / "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(receipt["status"], journal_status)
                self.assertTrue(receipt["strict_inventory"])
                self.assertEqual(len(receipt["original_units"]), 2)
                self.assertFalse(receipt["live_no_drain_authorized"])
                self._assert_unchanged(originals)

                # The Controller dispatcher is recreated against the same
                # durable disposable SQLite database; the Agent reconnects
                # using its actual HTTP client and existing credential.
                agent.controller._restart_controller_dispatcher()
                resumed = heartbeat()
                self.assertEqual(resumed["agent_id"], first["agent_id"])
                self._assert_unchanged(originals)

    def test_real_dashboard_and_hybrid_worker_restart_around_disposable_update(self):
        """Run actual DSM entrypoints under disposable systemd, never on DSM hosts.

        This validates the actual server_part22.py Dashboard entrypoint,
        credentialed Linux Agent HTTP against its integrated route, and Worker
        process restart around the guarded update.sh main() fixture. The Worker
        remains non-hybrid, and Agent host inventory/mutations are blocked by
        the reused fixture. Not a live no-drain update or complete Agent daemon.
        """
        import socket
        import sys
        from urllib.request import urlopen
        from urllib.error import URLError
        from update_game_uptime_main_path_test import MainPathRehearsalTest
        import update_game_uptime_agent_runtime_restart_test as agent_fixture_module

        # Reuse real ephemeral SQLite pairing/credentials, but route the Agent
        # to the ACTUAL production Controller HTTP composition instead of the
        # fixture's simplified dispatcher listener.
        agent_fixture = agent_fixture_module.LinuxAgentProcessHeartbeatTests(
            "test_real_agent_process_reconnects_to_restarted_controller")
        agent_fixture.setUp()
        self.addCleanup(agent_fixture.doCleanups)
        agent_fixture.controller._stop_http()

        original_games = [self._start("dashboard-game-a"),
                          self._start("dashboard-game-b")]
        root = self.workspace / "isolated-control-plane"
        for directory in ("dashboard/state", "data", "logs",
                          "runtime/hybrid-agent-state", "config"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        self.assertFalse((root / "config/agent.conf").exists())
        self.assertFalse((root / "runtime/hybrid-agent-state/agent.json").exists())

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        ping = f"http://127.0.0.1:{port}/ping"
        pythonpath = os.pathsep.join(str(p) for p in (
            ROOT, ROOT / "database", ROOT / "dashboard",
            ROOT / "core", ROOT / "agents/linux/runtime",
        ))
        common = (
            f"--setenv=DSM_ROOT={root}",
            f"--setenv=DSM_DATABASE={agent_fixture.controller.db_path}",
            "--setenv=DSM_DATABASE_DRIVER=sqlite",
            f"--setenv=PYTHONPATH={pythonpath}",
        )

        def start_control(role, generation):
            unit = f"{self.prefix}-{role}-{generation}.service"
            args = ["systemd-run", "--unit", unit[:-8], "--collect",
                    "--property=Type=simple",
                    "--property=NoNewPrivileges=yes",
                    "--property=ProtectSystem=strict",
                    f"--property=ReadWritePaths={self.workspace}",
                    f"--property=ReadWritePaths={agent_fixture.controller.db_path.parent}",
                    "--property=IPAddressDeny=any",
                    "--property=IPAddressAllow=localhost",
                    *common]
            if role == "dashboard":
                args.extend((
                    "--setenv=DASHBOARD_HOST=127.0.0.1",
                    f"--setenv=DASHBOARD_PORT={port}",
                    # Canonical systemd/dsm-dashboard.service ExecStart.
                    sys.executable, str(ROOT / "dashboard/server_part22.py"),
                ))
            else:
                args.extend((
                    "--setenv=DSM_HYBRID_HEARTBEAT_SECONDS=10",
                    sys.executable,
                    str(ROOT / "dashboard/workers/hybrid_agent_worker.py"),
                ))
            self._run(*args)
            self.units.append(unit)
            for _ in range(90):
                snap = self._snapshot(unit)
                if snap["state"] == "active" and snap["pid"] > 1:
                    if role != "dashboard":
                        return snap
                    try:
                        with urlopen(ping, timeout=0.5) as response:
                            content = json.loads(response.read())
                            if response.status == 200 and content.get("status") == "ok":
                                return snap
                    except (OSError, ValueError, URLError):
                        pass
                if snap["state"] == "failed":
                    break
                time.sleep(0.1)
            status = subprocess.run(
                ("systemctl", "status", unit, "--no-pager"),
                text=True, capture_output=True, check=False, timeout=8)
            self.fail(f"isolated {role} failed startup: {status.stdout[-1400:]}")

        def stop_control(unit):
            self._run("systemctl", "stop", unit)
            for _ in range(50):
                state = self._snapshot(unit)
                if state["state"] in ("inactive", "failed"):
                    return
                time.sleep(0.1)
            self.fail(f"isolated control-plane unit did not stop: {unit}")

        def check_current(control):
            self._assert_unchanged(original_games)
            for entry in control.values():
                self.assertEqual(self._snapshot(entry["unit"]), entry)
                cmdline = (Path("/proc") / str(entry["pid"]) / "cmdline").read_bytes()
                self.assertIn(b"hybrid_agent_worker.py" if "worker" in entry["unit"]
                              else b"dashboard/server_part22.py", cmdline)
            with urlopen(ping, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["status"], "ok")

        def check_authenticated_agent(*, rejected=False):
            # Separate Agent interpreter, real config/urllib heartbeat and
            # no host discovery or mutation (the existing fixture forbids it).
            agent_fixture.controller.url = (
                f"http://127.0.0.1:{port}/api/agent/heartbeat")
            # Keep this phase telemetry-only: new Controller enrollment can
            # return an operational Doctor command, which must never be
            # executed by an isolated update acceptance test.
            result = agent_fixture.invoke(invalid_secret=rejected, read_only=True)
            if rejected:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Controller rejected request (401)",
                              result.stderr[-1400:])
                self._assert_unchanged(original_games)
                return
            self.assertEqual(result.returncode, 0,
                             result.stderr[-1400:] + result.stdout[-600:])
            details = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(details["wire_compatible"])
            self.assertFalse(details["live_no_drain_authorized"])
            self.assertEqual(details["agent_id"], agent_fixture.controller.agent_id)
            self.assertEqual(details["health_status"], "online")
            self._assert_unchanged(original_games)

        current = {
            "dashboard": start_control("dashboard", "before"),
            "worker": start_control("worker", "before"),
        }
        check_current(current)
        check_authenticated_agent()
        check_authenticated_agent(rejected=True)

        for generation, mode, expected, journal in (
            ("after-success", "no_drain_success", "2.0.999-fixture", "verified"),
            ("after-rollback", "no_drain_fail_after_apply",
             "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(mode=mode):
                main = MainPathRehearsalTest(
                    "test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains")
                main.setUp()
                self.addCleanup(main.doCleanups)
                main.prepare_no_drain_fixture()
                result = main_rehearsal(main.root, mode)
                self.assertEqual(result.returncode, 0 if mode == "no_drain_success" else 2,
                                 result.stdout[-900:] + result.stderr[-900:])
                self.assertEqual((main.installed / "version").read_text().strip(), expected)
                self.assertEqual(main.world.read_bytes(), b"saved-world-private-test")
                self.assertEqual(main.upload.read_bytes(),
                                 b"in-flight-upload-private-test")
                self.assertFalse((main.root / "steps").exists())
                receipt = json.loads((
                    main.root / "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(receipt["status"], journal)
                self.assertFalse(receipt["live_no_drain_authorized"])
                check_current(current)

                # A deliberately orchestrated test-only control-plane restart;
                # production update.sh is NOT wired to these actual services.
                for service in ("worker", "dashboard"):
                    stop_control(current[service]["unit"])
                self._assert_unchanged(original_games)
                current = {
                    "dashboard": start_control("dashboard", generation),
                    "worker": start_control("worker", generation),
                }
                check_current(current)
                check_authenticated_agent()
                self.assertFalse((root / "config/agent.conf").exists())

        self.assertFalse((root / "runtime/hybrid-agent-state/agent.json").exists())
        self.assertFalse(Path("/opt/dsm/runtime/hybrid-instance-storage").exists())

    def test_real_worker_supervisor_group_restarts_without_draining_game_units(self):
        """Exercise unchanged worker.sh, nine harmless children, and real systemd.

        Production worker children are NEVER started. Every child executable
        is a self-contained sleep fixture inside a private, owner-marked /tmp
        root. The worker.sh bytes and lifecycle are real; operational worker
        code, database access and host reconciliation are out of scope.
        """
        import signal
        from update_game_uptime_main_path_test import MainPathRehearsalTest

        originals = [self._start("supervised-game-a"),
                     self._start("supervised-game-b")]
        fake_root = self.workspace / "supervisor-only-clone"
        workers = fake_root / "dashboard" / "workers"
        workers.mkdir(parents=True, mode=0o700)
        (fake_root / "logs").mkdir(mode=0o700)

        source = ROOT / "dashboard" / "workers" / "worker.sh"
        supervisor_script = workers / "worker.sh"
        supervisor_script.write_bytes(source.read_bytes())
        supervisor_script.chmod(0o700)
        self.assertEqual(source.read_bytes(), supervisor_script.read_bytes())
        expected_workers = (
            "scheduler_worker.sh",
            "automation_worker.py",
            "content_update_worker.py",
            "maintenance_worker.py",
            "observability_retention_worker.py",
            "content_upload_retention_worker.py",
            "database_intelligence_worker.py",
            "hybrid_agent_worker.py",
            "hybrid_customer_workspace_worker.py",
        )
        (workers / "scheduler_worker.sh").write_text(
            "#!/usr/bin/env bash\nexec /usr/bin/sleep 180\n", encoding="utf-8")
        (workers / "scheduler_worker.sh").chmod(0o700)
        for name in expected_workers[1:]:
            stub = workers / name
            stub.write_text(
                "import os, time\n"
                "from pathlib import Path\n"
                "if Path(__file__).name == 'hybrid_agent_worker.py':\n"
                "    assert os.environ.get('CAPIVARA_AGENT_MODE') == 'hybrid'\n"
                "    assert os.environ.get('CAPIVARA_DSM_ROOT') == "
                + repr(str(fake_root)) + "\n"
                "    assert os.environ.get('CAPIVARA_STEAM_HOME') == "
                + repr(str(fake_root)) + "\n"
                "time.sleep(180)\n", encoding="utf-8")

        unit = f"{self.prefix}-supervisor-clone.service"
        self._run(
            "systemd-run", "--unit", unit[:-8], "--collect",
            "--property=Type=simple", "--property=Restart=on-failure",
            "--property=RestartSec=1s",
            "--property=KillMode=control-group",
            "--property=NoNewPrivileges=yes",
            "--property=ProtectSystem=strict",
            f"--property=ReadWritePaths={fake_root}",
            "--property=IPAddressDeny=any",
            "--setenv=PYTHONDONTWRITEBYTECODE=1",
            f"--setenv=DSM_ROOT={fake_root}",
            "/usr/bin/bash", str(supervisor_script),
        )
        self.units.append(unit)
        log = fake_root / "logs" / "dashboard_worker.log"

        def running_snapshot(exclude_pid=0):
            for _ in range(100):
                snap = self._snapshot(unit)
                if (snap["state"] == "active"
                    and snap["pid"] > 1
                    and snap["started"] > 0
                    and snap["pid"] != exclude_pid):
                    children_file = (Path("/proc") / str(snap["pid"]) /
                                     "task" / str(snap["pid"]) / "children")
                    try:
                        children = [int(x) for x in
                                    children_file.read_text().strip().split()]
                    except OSError:
                        children = []
                    if len(children) == len(expected_workers):
                        return snap, children
                time.sleep(0.1)
            self.fail("real worker.sh never supervised all nine disposable children")

        before, children = running_snapshot()
        self._assert_unchanged(originals)
        self.assertTrue(log.exists())
        for name in expected_workers:
            self.assertIn(f"Iniciando {name}", log.read_text())

        for mode, version, status in (
            ("no_drain_success", "2.0.999-fixture", "verified"),
            ("no_drain_fail_after_apply", "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(mode=mode):
                fixture = MainPathRehearsalTest(
                    "test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains")
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                fixture.prepare_no_drain_fixture()
                result = main_rehearsal(fixture.root, mode)
                self.assertEqual(
                    result.returncode,
                    0 if mode == "no_drain_success" else 2,
                    result.stderr[-900:] + result.stdout[-900:],
                )
                self.assertEqual(
                    (fixture.installed / "version").read_text().strip(), version)
                receipt = json.loads((
                    fixture.root /
                    "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(receipt["status"], status)
                self.assertFalse(receipt["live_no_drain_authorized"])
                self.assertEqual(fixture.world.read_bytes(),
                                 b"saved-world-private-test")
                self.assertEqual(fixture.upload.read_bytes(),
                                 b"in-flight-upload-private-test")
                self.assertFalse((fixture.root / "steps").exists())
                self.assertEqual(self._snapshot(unit), before)
                self._assert_unchanged(originals)

        # Prove a REAL child of the transient supervisor can trigger the
        # production shell's wait -n -> exit 1 -> systemd Restart=on-failure.
        # Never send a signal to a PID without private script and cgroup proof.
        candidate = None
        for pid in children:
            proc = Path("/proc") / str(pid)
            try:
                command = (proc / "cmdline").read_bytes()
                cgroup = (proc / "cgroup").read_text()
            except OSError:
                continue
            if (str(workers / "automation_worker.py").encode() in command
                and unit in cgroup):
                candidate = pid
                break
        self.assertIsNotNone(candidate, "no verified disposable child to terminate")
        os.kill(candidate, signal.SIGTERM)
        after, recreated_children = running_snapshot(exclude_pid=before["pid"])
        self.assertNotEqual(before["pid"], after["pid"])
        self.assertEqual(len(recreated_children), len(expected_workers))
        self.assertIn("Worker filho encerrou inesperadamente", log.read_text())
        self._assert_unchanged(originals)
        self.assertFalse((fake_root / "config" / "agent.conf").exists())

    def test_two_real_systemd_processes_survive_actual_updater_file_functions(self):
        """Run actual update.sh backup/staging/apply/rollback on fake /tmp install."""
        originals = [self._start("real-alpha"), self._start("real-beta")]
        fake = self.workspace/"real-update-fixture"
        create_tiny_release_fixture(fake)

        def run(mode):
            completed = run_real_update_fns(fake, mode)
            if completed.returncode:
                raise RuntimeError(
                    f"real update.sh {mode} function failed: "
                    +completed.stderr[-350:]
                )

        run("prepare")
        journal = self.workspace/"real-update-journal"
        journal.mkdir(mode=0o700)

        outcome = transaction.execute(
            journal,
            [unit["unit"] for unit in originals],
            inspect=self._snapshot,
            apply=lambda: run("apply"),
            rollback=lambda: run("rollback"),
        )
        self.assertEqual(outcome["status"], "verified")
        self.assertFalse(outcome["live_no_drain_authorized"])
        self.assertEqual((fake/"installed/version").read_text(), "2.0.999-fixture")
        self.assertEqual(
            (fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
            b"saved-world-private-test",
        )
        self._assert_unchanged(originals)

        # Rehearse the real update.sh rollback, still leaving systemd PIDs intact.
        run("rollback")
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self._assert_unchanged(originals)

        def fail_after_real_file_replacement():
            run("apply")
            raise RuntimeError("fault injected after actual update.sh apply")

        failure_journal = self.workspace/"real-update-failure-journal"
        failure_journal.mkdir(mode=0o700)
        with self.assertRaisesRegex(transaction.TransactionSafetyError, "rollback completed"):
            transaction.execute(
                failure_journal,
                [unit["unit"] for unit in originals],
                inspect=self._snapshot,
                apply=fail_after_real_file_replacement,
                rollback=lambda: run("rollback"),
            )
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self._assert_unchanged(originals)
        with (failure_journal/"game-uptime-transaction.json").open() as f:
            self.assertEqual(json.load(f)["status"], "rolled_back")

    def test_two_transient_game_processes_survive_isolated_change_and_rollback(self):
        originals = [self._start("alpha"), self._start("beta")]
        installed = self.workspace/"installed"
        target = self.workspace/"target"
        installed.mkdir(mode=0o700)  # Also used as the private transaction journal.
        target.mkdir()
        for root, value in ((installed,"original"),(target,"updated")):
            path = root/"dashboard/web/status.js"
            path.parent.mkdir(parents=True)
            path.write_text(value)

        impact = plan.analyze(installed,target)
        self.assertEqual(impact["classification"],"review_only")
        self.assertFalse(impact["live_no_drain_authorized"])
        # Exercise the reusable transaction journal and PID invariants, not
        # the production update.sh (which still drains all game instances).
        snapshot = installed/"dashboard/web/status.js"

        def write_content(content):
            temp = snapshot.with_name(snapshot.name+".candidate")
            temp.write_text(content)
            os.replace(temp, snapshot)

        completed = transaction.execute(
            self.workspace/"installed",
            [unit["unit"] for unit in originals],
            inspect=lambda unit: self._snapshot(unit),
            apply=lambda: write_content("updated"),
            rollback=lambda: write_content("original"),
        )
        self.assertEqual(completed["status"], "verified")
        self.assertFalse(completed["live_no_drain_authorized"])
        self.assertEqual(snapshot.read_text(), "updated")
        self._assert_unchanged(originals)

        # An apply failure must roll back the modified files, while both
        # disposable units preserve PID and start-time identity.
        rollback_stage = self.workspace/"rollback-fixture"
        rollback_stage.mkdir(mode=0o700)

        def failed_change():
            write_content("bad-candidate")
            raise ValueError("simulated update failure")

        with self.assertRaisesRegex(transaction.TransactionSafetyError, "rollback completed"):
            transaction.execute(
                rollback_stage,
                [unit["unit"] for unit in originals],
                inspect=lambda unit: self._snapshot(unit),
                apply=failed_change,
                rollback=lambda: write_content("original"),
            )
        self.assertEqual(snapshot.read_text(), "original")
        self._assert_unchanged(originals)
        recorded = json.loads((rollback_stage/"game-uptime-transaction.json").read_text())
        self.assertEqual(recorded["status"], "rolled_back")

        # Unknown runtime change never becomes an authorized no-drain update.
        runtime = installed/"agents/linux/runtime/worker.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("before")
        candidate = target/"agents/linux/runtime/worker.py"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("after")
        impact = plan.analyze(installed,target)
        self.assertTrue(impact["requires_game_drain"])
        self.assertFalse(impact["live_no_drain_authorized"])
        self._assert_unchanged(originals)

    def test_pinned_minecraft_console_supervisor_survives_fixture_apply_and_rollback(self):
        """Run the real console supervisor from a versioned path under transient systemd."""
        import hashlib
        import socket
        import sys
        source = ROOT/"agents/linux/runtime/console_supervisor.py"
        stage_loader = SourceFileLoader(
            "dsm928_supervisor_stage_systemd",
            str(ROOT/"update-manager/game-uptime-supervisor-stage.py"),
        )
        stage_spec = importlib.util.spec_from_loader(stage_loader.name, stage_loader)
        stage_module = importlib.util.module_from_spec(stage_spec)
        stage_loader.exec_module(stage_module)
        versions = self.workspace/"pinned-supervisors"
        versions.mkdir(mode=0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        staged = stage_module.stage_supervisor(source, versions, expected_sha256=digest)
        pinned = Path(staged["path"])
        self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
        self.assertFalse(staged["live_no_drain_authorized"])
        sock_path = self.workspace/"minecraft-console.sock"
        unit = f"{self.prefix}-pinned-minecraft.service"
        self._run("systemd-run", "--unit", unit[:-8], "--collect",
                  "--property=Type=simple", sys.executable, str(pinned),
                  "--socket", str(sock_path), "--", "/usr/bin/sleep", "180")
        self.units.append(unit)
        for _ in range(50):
            snap = self._snapshot(unit)
            if snap["state"] == "active" and snap["pid"] > 1 and snap["started"] > 0 and sock_path.is_socket():
                break
            time.sleep(0.1)
        else:
            self.fail("disposable versioned console supervisor did not start")
        original = self._snapshot(unit)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(sock_path))
            client.sendall(b"status\n")
            self.assertEqual(client.recv(128), b"OK\n")
        self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
        fake = self.workspace/"pinned-updater-fixture"
        create_tiny_release_fixture(fake)
        for phase in ("prepare", "apply", "rollback"):
            result = run_real_update_fns(fake, phase)
            self.assertEqual(result.returncode, 0, result.stderr[-800:])
            self.assertEqual(self._snapshot(unit), original)
            self.assertTrue(sock_path.is_socket())
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
        self.assertFalse(staged["systemd_integrated"])
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")


    def test_controller_http_surrogate_restarts_while_pinned_supervisor_survives_rollback(self):
        """Isolated HTTP control-plane *surrogate* restart + real file rollback.

        Exercises the real console_supervisor.py and update.sh file functions,
        NOT the real DSM Controller, real Minecraft JVM or no-drain main().
        """
        import hashlib
        import socket
        import sys
        from urllib.request import urlopen
        from urllib.error import URLError

        source = ROOT/"agents/linux/runtime/console_supervisor.py"
        loader = SourceFileLoader("dsm928_supervisor_stage_control_restart",
                                  str(ROOT/"update-manager/game-uptime-supervisor-stage.py"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stage = importlib.util.module_from_spec(spec)
        loader.exec_module(stage)
        versions = self.workspace/"control-restart-pinned"
        versions.mkdir(mode=0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        pinned = Path(stage.stage_supervisor(source, versions, expected_sha256=digest)["path"])
        sock = self.workspace/"stable-console.sock"
        game_unit = f"{self.prefix}-stable-game.service"
        self._run("systemd-run", "--unit", game_unit[:-8], "--collect",
                  "--property=Type=simple", sys.executable, str(pinned),
                  "--socket", str(sock), "--", "/usr/bin/sleep", "180")
        self.units.append(game_unit)
        for _ in range(60):
            prior = self._snapshot(game_unit)
            if prior["state"] == "active" and prior["pid"] > 1 and prior["started"] > 0 and sock.is_socket():
                break
            time.sleep(0.1)
        else:
            self.fail("pinned game supervisor failed to become ready")

        def check_game():
            self.assertEqual(self._snapshot(game_unit), prior)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(sock))
                client.sendall(b"status\n")
                self.assertEqual(client.recv(32), b"OK\n")

        # Only a tiny, owner-marked test installation under /tmp is modified.
        fake = self.workspace/"control-restart-release-fixture"
        create_tiny_release_fixture(fake)
        web_root = fake/"installed/dashboard/web"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
            bound.bind(("127.0.0.1", 0))
            port = bound.getsockname()[1]
        url = "http://127.0.0.1:%d/presentation.js" % port

        def controller_start(suffix):
            name = f"{self.prefix}-http-{suffix}.service"
            self._run("systemd-run", "--unit", name[:-8], "--collect",
                      "--property=Type=simple",
                      sys.executable, "-m", "http.server", str(port),
                      "--bind", "127.0.0.1", "--directory", str(web_root))
            self.units.append(name)
            return name

        def content(expected):
            for _ in range(60):
                try:
                    with urlopen(url, timeout=1) as response:
                        body = response.read().decode("utf-8")
                    if body == expected:
                        return
                except (URLError, TimeoutError, OSError):
                    pass
                time.sleep(0.1)
            self.fail("disposable HTTP controller surrogate did not serve " + expected)

        def update_step(step):
            completed = run_real_update_fns(fake, step)
            if completed.returncode != 0:
                raise RuntimeError("fixture " + step + " failed: " + completed.stderr[-350:])

        controller_old = controller_start("old")
        content("from-2.0.998-fixture")
        check_game()
        update_step("prepare")
        journal = self.workspace/"control-restart-journal"
        journal.mkdir(mode=0o700)
        controller_new = [None]
        controller_restored = [None]

        def update_then_inject_failure():
            self._run("systemctl", "stop", controller_old)
            check_game()
            update_step("apply")
            check_game()
            controller_new[0] = controller_start("new")
            content("from-2.0.999-fixture")
            check_game()
            raise RuntimeError("injected failure after disposable Controller restart")

        def compensate():
            if controller_new[0] is not None:
                self._run("systemctl", "stop", controller_new[0])
            update_step("rollback")
            controller_restored[0] = controller_start("restored")
            content("from-2.0.998-fixture")
            check_game()

        with self.assertRaisesRegex(transaction.TransactionSafetyError, "rollback completed"):
            transaction.execute(journal, [game_unit], inspect=self._snapshot,
                                apply=update_then_inject_failure,
                                rollback=compensate)
        check_game()
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual((fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
                         b"saved-world-private-test")
        self.assertEqual((fake/"installed/data/database.txt").read_text(), "db durable")
        self.assertEqual(json.loads((journal/"game-uptime-transaction.json").read_text())["status"],
                         "rolled_back")
        self.assertIsNotNone(controller_restored[0])


    def test_disposable_systemd_pids_survive_interrupted_apply_and_operator_rollback(self):
        """Recover a partial file transaction with real transient systemd PIDs.

        The crash here is SystemExit. A separate unit test uses actual SIGKILL.
        """
        originals = [self._start("recovery-alpha"), self._start("recovery-beta")]
        fake = self.workspace/"recovery-real-updater-functions"
        create_tiny_release_fixture(fake)

        def run(step):
            result = run_real_update_fns(fake, step)
            if result.returncode:
                raise RuntimeError("fixture " + step + " failed: " + result.stderr[-450:])

        run("prepare")
        journal = self.workspace/"interrupted-real-systemd-journal"
        journal.mkdir(mode=0o700)

        def interrupted_apply():
            run("apply")
            self._assert_unchanged(originals)
            raise SystemExit(47)

        with self.assertRaises(SystemExit):
            transaction.execute(
                journal,
                [row["unit"] for row in originals],
                inspect=self._snapshot,
                apply=interrupted_apply,
                rollback=lambda: run("rollback"),
            )
        self.assertEqual((fake/"installed/version").read_text(), "2.0.999-fixture")
        self.assertEqual(json.loads((journal/"game-uptime-transaction.json").read_text())["status"],
                         "prepared")
        self._assert_unchanged(originals)

        outcome = transaction.recover_interrupted(
            journal, [row["unit"] for row in originals],
            inspect=self._snapshot, rollback=lambda: run("rollback"),
            operator_reviewed=True,
        )
        self.assertEqual(outcome["status"], "recovered_rollback")
        self.assertFalse(outcome["live_no_drain_authorized"])
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual((fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
                         b"saved-world-private-test")
        self.assertEqual((fake/"installed/data/database.txt").read_text(), "db durable")
        self.assertEqual(json.loads((journal/"game-uptime-transaction.json").read_text())["status"],
                         "recovered_rollback")
        self._assert_unchanged(originals)


    def test_minecraft_supervisor_and_dayz_udp_standin_survive_apply_and_rollback(self):
        """Two distinct disposable game-shaped units remain responsive.

        Minecraft uses actual SHA-pinned console_supervisor.py with a sleep
        child (not a Minecraft JVM). DayZ uses a UDP echo stand-in (not DayZ).
        updater functions operate exclusively on an owned /tmp fixture.
        """
        import hashlib
        import socket
        import sys

        source = ROOT / "agents/linux/runtime/console_supervisor.py"
        loader = SourceFileLoader(
            "dsm928_supervisor_stage_dual_game",
            str(ROOT / "update-manager/game-uptime-supervisor-stage.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stage = importlib.util.module_from_spec(spec)
        loader.exec_module(stage)
        versions = self.workspace / "dual-game-pinned-versions"
        versions.mkdir(mode=0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        staged = stage.stage_supervisor(
            source, versions, expected_sha256=digest)
        pinned = Path(staged["path"])
        self.assertFalse(staged["live_no_drain_authorized"])

        minecraft_sock = self.workspace / "dual-game-console.sock"
        minecraft_unit = f"{self.prefix}-minecraft-pinned.service"
        self._run(
            "systemd-run", "--unit", minecraft_unit[:-8], "--collect",
            "--property=Type=simple", sys.executable, str(pinned),
            "--socket", str(minecraft_sock), "--", "/usr/bin/sleep", "180",
        )
        self.units.append(minecraft_unit)

        dayz_script = self.workspace / "dayz-udp-standin.py"
        dayz_script.write_text(
            "import socket,sys\n"
            "sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n"
            "sock.bind(('127.0.0.1',int(sys.argv[1])))\n"
            "while True:\n"
            " data,peer=sock.recvfrom(4096)\n"
            " if data==b'dayz-fixture-query':\n"
            "  sock.sendto(b'dayz-fixture-ok',peer)\n",
            encoding="utf-8",
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            dayz_port = reserve.getsockname()[1]
        dayz_unit = f"{self.prefix}-dayz-udp.service"
        self._run(
            "systemd-run", "--unit", dayz_unit[:-8], "--collect",
            "--property=Type=simple", sys.executable, str(dayz_script),
            str(dayz_port),
        )
        self.units.append(dayz_unit)

        def query_dayz():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.5)
                client.sendto(b"dayz-fixture-query", ("127.0.0.1", dayz_port))
                return client.recvfrom(128)[0]

        for _ in range(60):
            minecraft = self._snapshot(minecraft_unit)
            dayz = self._snapshot(dayz_unit)
            ready = (
                minecraft["state"] == "active" and minecraft["pid"] > 1
                and minecraft["started"] > 0 and dayz["state"] == "active"
                and dayz["pid"] > 1 and dayz["started"] > 0
                and minecraft_sock.is_socket()
            )
            if ready:
                try:
                    if query_dayz() == b"dayz-fixture-ok":
                        break
                except (socket.timeout, OSError):
                    pass
            time.sleep(0.1)
        else:
            self.fail("disposable supervisor or UDP stand-in not ready")
        originals = [minecraft, dayz]

        # Verify the *complete* transient game-unit set, not just these
        # recorded PIDs. Derive an independent witness from real systemd
        # directives without persisting potentially sensitive ExecStart data.
        def list_active_game_standins():
            result = self._run(
                "systemctl", "list-units", "--all", "--type=service",
                "--state=active", "--plain", "--no-legend",
                "dsm928-e2e-*.service",
            )
            return [line.split()[0] for line in result.stdout.splitlines()
                    if line.strip() and line.split()[0].endswith(".service")]

        def systemd_witness(unit):
            result = self._snapshot(unit)
            properties = self._run(
                "systemctl", "show", unit,
                "-p", "ExecStart", "-p", "FragmentPath",
                "-p", "DropInPaths", "-p", "User", "-p", "WorkingDirectory",
                "-p", "PartOf", "-p", "BindsTo", "-p", "PropagatesStopTo",
            )
            result["unit_config_sha256"] = hashlib.sha256(
                properties.stdout.encode("utf-8")
            ).hexdigest()
            return result

        def check_both():
            self._assert_unchanged(originals)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(),
                             digest)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(minecraft_sock))
                client.sendall(b"status\n")
                self.assertEqual(client.recv(128), b"OK\n")
            self.assertEqual(query_dayz(), b"dayz-fixture-ok")

        def updater(workspace, phase):
            result = run_real_update_fns(workspace, phase)
            self.assertEqual(result.returncode, 0,
                             (phase, result.stdout[-500:], result.stderr[-700:]))

        check_both()
        for mode in ("success", "fault_after_apply"):
            with self.subTest(mode=mode):
                fixture = self.workspace / ("dual-game-" + mode)
                create_tiny_release_fixture(fixture)
                updater(fixture, "prepare")
                check_both()
                journal = self.workspace / ("dual-game-transaction-" + mode)
                journal.mkdir(mode=0o700)

                def apply():
                    updater(fixture, "apply")
                    self.assertEqual(
                        (fixture / "installed/version").read_text(),
                        "2.0.999-fixture",
                    )
                    check_both()
                    if mode == "fault_after_apply":
                        raise RuntimeError("injected after files swapped")

                def rollback():
                    updater(fixture, "rollback")
                    check_both()

                handoff = transaction.attest_handoff(
                    [minecraft_unit, dayz_unit], inspect=systemd_witness,
                    list_units=list_active_game_standins,
                )
                if mode == "success":
                    result = transaction.execute(
                        journal, [minecraft_unit, dayz_unit],
                        inspect=systemd_witness, apply=apply, rollback=rollback,
                        handoff=handoff, list_units=list_active_game_standins,
                    )
                    receipt = json.loads(
                        (journal / "game-uptime-transaction.json").read_text())
                    self.assertTrue(receipt["strict_inventory"])
                    self.assertEqual(len(receipt["original_units"]), 2)
                    self.assertEqual(len(receipt["original_units_sha256"]), 64)
                    self.assertEqual(result["status"], "verified")
                    self.assertEqual(
                        (fixture / "installed/version").read_text(),
                        "2.0.999-fixture",
                    )
                else:
                    with self.assertRaisesRegex(
                        transaction.TransactionSafetyError, "rollback completed"
                    ):
                        transaction.execute(
                            journal, [minecraft_unit, dayz_unit],
                            inspect=systemd_witness, apply=apply,
                            rollback=rollback, handoff=handoff,
                            list_units=list_active_game_standins,
                        )
                    self.assertEqual(
                        (fixture / "installed/version").read_text(),
                        "2.0.998-fixture",
                    )
                    self.assertEqual(
                        json.loads(
                            (journal / "game-uptime-transaction.json").read_text()
                        )["status"], "rolled_back",
                    )
                self.assertEqual(
                    (fixture /
                     "installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat"
                     ).read_bytes(), b"saved-world-private-test",
                )
                self.assertEqual(
                    (fixture / "installed/data/database.txt").read_text(),
                    "db durable",
                )
                check_both()


    def test_pinned_minecraft_supervisor_runs_as_unprivileged_systemd_user(self):
        """Prove real service-user access to SHA-pinned code in a throwaway unit.

        A transient dsm928-e2e unit uses User=nobody and runs a console
        supervisor with /usr/bin/sleep as its child, NOT a Minecraft JVM.
        No Capivara game unit or host systemd materializer is modified.
        """
        import hashlib
        import pwd
        import socket
        import sys

        try:
            account = pwd.getpwnam("nobody")
        except KeyError:
            self.skipTest("disposable runner lacks nobody service account")
        if account.pw_uid == os.geteuid():
            self.skipTest("test requires distinct non-root service account")
        runtime = ROOT / "agents/linux/runtime"
        if str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))
        from materializers.base import MaterializerError
        from materializers.systemd import render_unit

        loader = SourceFileLoader(
            "dsm928_unprivileged_supervisor_stage",
            str(ROOT / "update-manager/game-uptime-supervisor-stage.py"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stage = importlib.util.module_from_spec(spec)
        loader.exec_module(stage)

        source = runtime / "console_supervisor.py"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        versions = self.workspace / "pinned-versions-unprivileged"
        versions.mkdir(mode=0o755)
        versions.chmod(0o755)
        staged = stage.stage_supervisor(source, versions, expected_sha256=digest)
        pinned = Path(staged["path"])
        self.assertEqual(pinned.stat().st_mode & 0o777, 0o444)
        pin = {"path": str(pinned), "sha256": digest}
        runtime_spec = {
            "instance_id": "fixture-minecraft-nobody",
            "agent_id": "disposable-agent",
            "runtime_id": "minecraft.java.neoforge",
            "game_id": "minecraft",
            "environment_id": "minecraft.java.neoforge",
            "user": account.pw_name,
            "working_directory": str(self.workspace),
            "executable": "/usr/bin/sleep",
            "arguments": ["180"],
        }

        # A 0700 ancestor, although readable as root, must not pass preflight.
        with self.assertRaisesRegex(MaterializerError, "not traversable"):
            render_unit(runtime_spec, pinned_supervisor_preview=pin)
        self.workspace.chmod(0o711)
        proposed = render_unit(runtime_spec, pinned_supervisor_preview=pin)
        self.assertIn("User=" + account.pw_name, proposed)
        self.assertIn('ExecStart="/usr/bin/python3" "' + str(pinned) + '"',
                      proposed)
        self.assertFalse(staged["live_no_drain_authorized"])

        sock_dir = self.workspace / "nobody-console"
        sock_dir.mkdir(mode=0o700)
        os.chown(sock_dir, account.pw_uid, account.pw_gid)
        sock = sock_dir / "console.sock"
        unit = f"{self.prefix}-unprivileged-minecraft.service"
        self._run(
            "systemd-run", "--unit", unit[:-8], "--collect",
            "--property=Type=simple", "--property=User=" + account.pw_name,
            "--property=NoNewPrivileges=yes",
            sys.executable, str(pinned),
            "--socket", str(sock), "--", "/usr/bin/sleep", "180",
        )
        self.units.append(unit)

        for _ in range(80):
            identity = self._snapshot(unit)
            if (identity["state"] == "active" and identity["pid"] > 1
                    and identity["started"] > 0 and sock.is_socket()):
                break
            time.sleep(0.1)
        else:
            self.fail("non-root pinned supervisor failed to start/read staged file")

        properties = self._run("systemctl", "show", unit, "-p", "User",
                               "-p", "ExecStart")
        self.assertIn("User=" + account.pw_name, properties.stdout)
        self.assertIn(str(pinned), properties.stdout)
        status = Path("/proc") / str(identity["pid"]) / "status"
        uid_line = next(
            line for line in status.read_text().splitlines()
            if line.startswith("Uid:"))
        self.assertEqual(int(uid_line.split()[1]), account.pw_uid)

        def verify_running():
            self.assertEqual(self._snapshot(unit), identity)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(),
                             digest)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(sock))
                client.sendall(b"status\n")
                self.assertEqual(client.recv(64), b"OK\n")

        verify_running()
        fixture = self.workspace / "unprivileged-pinned-updater-fixture"
        create_tiny_release_fixture(fixture)
        for phase in ("prepare", "apply", "rollback"):
            result = run_real_update_fns(fixture, phase)
            self.assertEqual(result.returncode, 0,
                             (phase, result.stderr[-450:]))
            verify_running()
        self.assertEqual(
            (fixture / "installed/version").read_text(),
            "2.0.998-fixture")


    def test_disposable_live_systemd_unit_file_swap_and_manual_restore_keep_pid(self):
        """Actually replace a /run/systemd/system unit in a clean CI runner.

        Only dsm928-e2e-* names with allowlisted /usr/bin/sleep commands
        qualify. No Capivara instance unit or update.sh is touched.
        """
        import hashlib

        loader = SourceFileLoader(
            "dsm928_file_swap_disposable_only",
            str(ROOT / "update-manager/game-uptime-systemd-swap.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        swap = importlib.util.module_from_spec(spec)
        loader.exec_module(swap)
        unit = f"{self.prefix}-file-swap.service"
        path = Path("/run/systemd/system") / unit
        marker = (
            "# DSM928_DISPOSABLE_UNIT_V1\n"
            f"# DSM928_UNIT={unit}\n"
            "[Unit]\nDescription=DSM928 isolated sleep test\n"
            "[Service]\nType=simple\n"
        )
        old = (marker + "ExecStart=/usr/bin/sleep 180\n").encode()
        new = (marker + "ExecStart=/usr/bin/sleep 170\n").encode()
        self.assertFalse(path.exists())
        self.assertFalse(path.is_symlink())
        journal = self.workspace / "real-systemd-unit-file-swap"
        journal.mkdir(mode=0o700)
        path.write_bytes(old)
        path.chmod(0o644)

        try:
            self._run("systemctl", "daemon-reload")
            self._run("systemctl", "start", unit)
            self.units.append(unit)
            for _ in range(50):
                baseline = self._snapshot(unit)
                if (baseline["state"] == "active" and baseline["pid"] > 1
                        and baseline["started"] > 0):
                    break
                time.sleep(0.1)
            else:
                self.fail("disposable unit did not become active")

            applied = swap.swap_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                candidate=new, expected_old_sha256=hashlib.sha256(old).hexdigest(),
                inspect=self._snapshot,
            )
            self.assertEqual(applied["status"], "applied")
            self.assertFalse(applied["live_no_drain_authorized"])
            self.assertEqual(path.read_bytes(), new)
            self.assertEqual(self._snapshot(unit), baseline)
            self.assertEqual(
                json.loads((journal / "dsm928-unit-swap.json").read_text())["status"],
                "applied",
            )
            shown = self._run("systemctl", "cat", unit)
            self.assertIn("ExecStart=/usr/bin/sleep 170", shown.stdout)
            restored = swap.restore_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                inspect=self._snapshot, operator_reviewed=True,
            )
            self.assertEqual(restored["status"], "restored")
            self.assertFalse(restored["live_no_drain_authorized"])
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(self._snapshot(unit), baseline)
            with self.assertRaises(swap.DisposableSwapError):
                swap.restore_unit(
                    journal, unit, unit_dir=Path("/run/systemd/system"),
                    inspect=self._snapshot, operator_reviewed=True,
                )
        finally:
            # Mandatory teardown of *this exact* disposable service only.
            subprocess.run(("systemctl", "stop", unit), timeout=15,
                           capture_output=True, text=True, check=False)
            if path.is_file() and not path.is_symlink():
                path.unlink()
            subprocess.run(("systemctl", "daemon-reload"), timeout=20,
                           capture_output=True, text=True, check=False)


    def test_actual_pinned_minecraft_supervisor_unit_swap_retains_old_live_revision(self):
        """Switch staged supervisor SHA in real disposable unit, no JVM/start.

        The currently running pinned Python console supervisor retains its
        original PID and /proc command line after daemon-reload. Unit files
        are restored before teardown, and both exact versions stay staged.
        """
        import hashlib
        import socket
        import sys

        stage_loader = SourceFileLoader(
            "dsm928_pinned_stage_systemd_swap",
            str(ROOT / "update-manager/game-uptime-supervisor-stage.py"))
        stage_spec = importlib.util.spec_from_loader(
            stage_loader.name, stage_loader)
        stage = importlib.util.module_from_spec(stage_spec)
        stage_loader.exec_module(stage)

        swap_loader = SourceFileLoader(
            "dsm928_pinned_systemd_swap_real_e2e",
            str(ROOT / "update-manager/game-uptime-systemd-swap.py"))
        swap_spec = importlib.util.spec_from_loader(
            swap_loader.name, swap_loader)
        swap = importlib.util.module_from_spec(swap_spec)
        swap_loader.exec_module(swap)

        journal = self.workspace / "pinned-real-file-swap"
        journal.mkdir(mode=0o700)
        versions = journal / "versions"
        versions.mkdir(mode=0o700)
        source = ROOT / "agents/linux/runtime/console_supervisor.py"
        v2_source = journal / "candidate-console-supervisor.py"
        v2_source.write_bytes(
            source.read_bytes() + b"\n# DSM928 disposable next revision\n")
        staged = []
        for source_file in (source, v2_source):
            digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
            result = stage.stage_supervisor(
                source_file, versions, expected_sha256=digest)
            staged.append(Path(result["path"]))
        self.assertNotEqual(staged[0], staged[1])

        sock = journal / "console.sock"
        unit = f"{self.prefix}-pinned-unit-swap.service"
        path = Path("/run/systemd/system") / unit
        header = (
            "# DSM928_DISPOSABLE_UNIT_V1\n"
            f"# DSM928_UNIT={unit}\n"
            "[Unit]\nDescription=DSM928 pinned supervisor test only\n"
            "[Service]\nType=simple\n"
        )
        def content(supervisor):
            return (header + "ExecStart=/usr/bin/python3 "
                    + str(supervisor) + " --socket " + str(sock)
                    + " -- /usr/bin/sleep 180\n").encode("utf-8")

        old, new = content(staged[0]), content(staged[1])
        self.assertFalse(path.exists())
        self.assertFalse(path.is_symlink())
        path.write_bytes(old)
        path.chmod(0o644)
        try:
            self._run("systemctl", "daemon-reload")
            self._run("systemctl", "start", unit)
            self.units.append(unit)
            for _ in range(70):
                identity = self._snapshot(unit)
                if (identity["state"] == "active" and identity["pid"] > 1
                        and identity["started"] > 0 and sock.is_socket()):
                    break
                time.sleep(0.1)
            else:
                self.fail("real pinned disposable supervisor did not start")

            cmdline = (Path("/proc") / str(identity["pid"]) /
                       "cmdline").read_bytes().split(b"\0")
            self.assertIn(os.fsencode(staged[0]), cmdline)
            self.assertNotIn(os.fsencode(staged[1]), cmdline)

            def check_live():
                self.assertEqual(self._snapshot(unit), identity)
                self.assertTrue(all(p.is_file() for p in staged))
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(3)
                    client.connect(str(sock))
                    client.sendall(b"status\n")
                    self.assertEqual(client.recv(64), b"OK\n")

            check_live()
            result = swap.swap_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                candidate=new,
                expected_old_sha256=hashlib.sha256(old).hexdigest(),
                inspect=self._snapshot,
            )
            self.assertEqual(result["status"], "applied")
            self.assertFalse(result["live_no_drain_authorized"])
            self.assertEqual(path.read_bytes(), new)
            self.assertIn(str(staged[1]),
                          self._run("systemctl", "cat", unit).stdout)
            # The unit is configured for a new supervisor only on a future
            # service start; the current old Python interpreter survives.
            self.assertIn(os.fsencode(staged[0]),
                          (Path("/proc") / str(identity["pid"]) /
                           "cmdline").read_bytes().split(b"\0"))
            check_live()

            restored = swap.restore_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                inspect=self._snapshot, operator_reviewed=True,
            )
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(path.read_bytes(), old)
            self.assertIn(str(staged[0]),
                          self._run("systemctl", "cat", unit).stdout)
            check_live()
            self.assertEqual(
                json.loads((journal / "dsm928-unit-swap.json").read_text())["status"],
                "restored",
            )
            self.assertEqual(
                hashlib.sha256(staged[0].read_bytes()).hexdigest(),
                staged[0].name.removeprefix("console-supervisor-").removesuffix(".py"),
            )
            self.assertEqual(
                hashlib.sha256(staged[1].read_bytes()).hexdigest(),
                staged[1].name.removeprefix("console-supervisor-").removesuffix(".py"),
            )
        finally:
            # Never leave this disposable pinned service/unit on the runner.
            subprocess.run(
                ("systemctl", "stop", unit), capture_output=True,
                text=True, timeout=15, check=False,
            )
            if path.is_file() and not path.is_symlink():
                path.unlink()
            subprocess.run(
                ("systemctl", "daemon-reload"), capture_output=True,
                text=True, timeout=20, check=False,
            )

