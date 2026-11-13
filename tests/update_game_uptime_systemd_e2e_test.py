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

    def test_two_transient_game_processes_survive_isolated_change_and_rollback(self):
        originals = [self._start("alpha"), self._start("beta")]
        installed = self.workspace/"installed"
        target = self.workspace/"target"
        installed.mkdir()
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
        rollback_stage.mkdir()

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


if __name__ == "__main__":
    unittest.main()
