"""Opt-in live-systemd, disposable-unit rehearsal for #928 (never runs DSM update).

Runs only with CAPIVARA_DSM928_SYSTEMD_E2E=1 and root; creates two uniquely
named NON-Capivara transient sleep units, so the game Agent cannot discover or
reconcile them. Exercises an isolated file transaction plus rollback with the
real systemd MainPID/start stamp invariant on both processes.
"""
from __future__ import annotations

import importlib.util
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


class DisposableSystemdNoDrainTest(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CAPIVARA_DSM928_SYSTEMD_E2E") != "1":
            self.skipTest("opt-in required: CAPIVARA_DSM928_SYSTEMD_E2E=1")
        if os.geteuid() != 0 or not shutil.which("systemd-run"):
            self.skipTest("requires root and systemd-run")
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
        # Rehearse ONLY a file replacement in a disposable tree; never invoke
        # the installed updater, whose no-drain path is not implemented.
        snapshot = installed/"dashboard/web/status.js"
        replacement = snapshot.with_name("status.js.candidate")
        replacement.write_text((target/"dashboard/web/status.js").read_text())
        os.replace(replacement,snapshot)
        self._assert_unchanged(originals)
        self.assertEqual(snapshot.read_text(),"updated")

        rollback = snapshot.with_name("status.js.rollback")
        rollback.write_text("original")
        os.replace(rollback,snapshot)
        self._assert_unchanged(originals)
        self.assertEqual(snapshot.read_text(),"original")

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
