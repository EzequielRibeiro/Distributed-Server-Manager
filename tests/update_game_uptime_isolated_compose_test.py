"""#928: disposable updater file functions and systemd swap in one transaction.

This unit test suite uses a fake systemd reload, exact /tmp fixture marker
and fake PIDs only. A separate root/systemd E2E tests real transient units.
"""
from __future__ import annotations

import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from update_game_uptime_real_update_functions_test import (
    create_tiny_release_fixture, run_real_update_fns,
)

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    loader = SourceFileLoader(name, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


compose = load("update-manager/game-uptime-isolated-compose.py",
               "dsm928_composite_unit_tests")
swap = load("update-manager/game-uptime-systemd-swap.py",
            "dsm928_swap_for_composite_unit_tests")

UNIT = "dsm928-e2e-minecraft-pinned.service"
DAYZ = "dsm928-e2e-dayz-sim.service"


def unit_content(seconds: int) -> bytes:
    return (
        "# DSM928_DISPOSABLE_UNIT_V1\n"
        f"# DSM928_UNIT={UNIT}\n"
        "[Unit]\nDescription=DSM928 isolated unit transaction\n"
        "[Service]\nType=simple\n"
        f"ExecStart=/usr/bin/sleep {seconds}\n"
    ).encode()


class IsolatedCompositionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dsm928-composed-fixture-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        create_tiny_release_fixture(self.root)
        self.units = self.root / "units"
        self.units.mkdir()
        self.installed = self.units / UNIT
        self.old = unit_content(180)
        self.new = unit_content(170)
        self.installed.write_bytes(self.old)
        self.states = {
            UNIT: {"unit": UNIT, "pid": 22001, "started": 901, "state": "active"},
            DAYZ: {"unit": DAYZ, "pid": 22002, "started": 902, "state": "active"},
        }
        self.reloads = 0
        self.inject_fault = None
        self.rollback_unit_failure = False

    def inspect(self, unit):
        return dict(self.states[unit])

    def reload(self):
        self.reloads += 1
        return True

    def updater(self, phase):
        result = run_real_update_fns(self.root, phase)
        if result.returncode:
            raise RuntimeError("disposable updater " + phase + ": " + result.stderr[-800:])

    def swap_unit(self):
        swap.swap_unit(
            self.root, UNIT, unit_dir=self.units, candidate=self.new,
            expected_old_sha256=hashlib.sha256(self.old).hexdigest(),
            inspect=self.inspect, runner=self.reload,
        )
        if self.inject_fault == "after_swap":
            raise RuntimeError("inject fault after unit swap")

    def restore_unit(self):
        if self.rollback_unit_failure:
            raise RuntimeError("inject failure restoring unit")
        journal = self.root / "dsm928-unit-swap.json"
        if not journal.exists():
            return
        report = json.loads(journal.read_text())
        if report["status"] in ("prepared", "applied"):
            swap.restore_unit(
                self.root, UNIT, unit_dir=self.units,
                inspect=self.inspect, runner=self.reload,
                operator_reviewed=True,
            )
        elif report["status"] != "rolled_back":
            raise RuntimeError("unsafe unit swap journal status")

    def verify(self):
        self.assertEqual(self.states[UNIT]["pid"], 22001)
        self.assertEqual(self.states[DAYZ]["pid"], 22002)
        self.assertEqual(
            (self.root / "installed/runtime/hybrid-instance-storage/minecraft005/"
             "world/level.dat").read_bytes(),
            b"saved-world-private-test",
        )
        self.assertEqual(
            (self.root / "installed/data/database.txt").read_text(),
            "db durable",
        )
        if self.inject_fault == "verify_new" and (
            self.root / "installed/version").read_text() == "2.0.999-fixture":
            raise RuntimeError("inject failed health check")

    def run_composed(self, *, apply_unit=None):
        return compose.execute(
            self.root, [UNIT, DAYZ], inspect=self.inspect,
            prepare_files=lambda: self.updater("prepare"),
            apply_files=lambda: self.updater("apply"),
            rollback_files=lambda: self.updater("rollback"),
            apply_unit=apply_unit or self.swap_unit,
            rollback_unit=self.restore_unit,
            verify=self.verify,
        )

    def test_success_composes_real_updater_functions_and_fake_reload(self):
        receipt = self.run_composed()
        self.assertEqual(receipt["status"], "verified")
        self.assertFalse(receipt["live_no_drain_authorized"])
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.999-fixture")
        self.assertEqual(self.installed.read_bytes(), self.new)
        self.assertEqual(self.reloads, 1)
        self.assertEqual(self.states[UNIT]["pid"], 22001)
        self.assertEqual(self.states[DAYZ]["pid"], 22002)
        receipt_path = self.root / "dsm928-composite-journal/game-uptime-transaction.json"
        self.assertEqual(json.loads(receipt_path.read_text())["status"], "verified")
        with self.assertRaisesRegex(compose.CompositeSafetyError, "existing composite"):
            self.run_composed()
        self.restore_unit()
        self.updater("rollback")
        self.assertEqual(self.installed.read_bytes(), self.old)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")

    def test_after_unit_swap_failure_restores_unit_and_update_files(self):
        self.inject_fault = "after_swap"
        with self.assertRaisesRegex(Exception, "rollback completed"):
            self.run_composed()
        self.assertEqual(self.installed.read_bytes(), self.old)
        self.assertEqual(self.reloads, 2)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")
        journal = self.root / "dsm928-composite-journal/game-uptime-transaction.json"
        self.assertEqual(json.loads(journal.read_text())["status"], "rolled_back")
        self.assertEqual(
            json.loads((self.root / "dsm928-unit-swap.json").read_text())["status"],
            "restored",
        )

    def test_before_unit_swap_failure_still_rolls_back_file_update(self):
        def raise_before():
            raise RuntimeError("inject error before systemd swap")
        with self.assertRaisesRegex(Exception, "rollback completed"):
            self.run_composed(apply_unit=raise_before)
        self.assertEqual(self.installed.read_bytes(), self.old)
        self.assertEqual(self.reloads, 0)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")

    def test_both_compensations_attempted_when_unit_restore_fails(self):
        self.inject_fault = "after_swap"
        self.rollback_unit_failure = True
        with self.assertRaisesRegex(Exception, "manual recovery required"):
            self.run_composed()
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual(self.installed.read_bytes(), self.new)
        journal = self.root / "dsm928-composite-journal/game-uptime-transaction.json"
        self.assertEqual(json.loads(journal.read_text())["status"],
                         "manual_recovery_required")

    def test_legacy_jvm_health_failure_compensates_without_restarting_units(self):
        self.inject_fault = "verify_new"
        with self.assertRaisesRegex(Exception, "rollback completed"):
            self.run_composed()
        self.assertEqual(self.installed.read_bytes(), self.old)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual(self.states[UNIT]["pid"], 22001)

    def test_refuse_missing_owner_and_production_game_unit(self):
        calls = []
        for units in ([UNIT, "capivara-instance-cli-000001-minecraft-005.service"],
                      [UNIT, UNIT]):
            with self.subTest(units=units):
                with self.assertRaisesRegex(compose.CompositeSafetyError, "only unique"):
                    compose.execute(
                        self.root, units, inspect=self.inspect,
                        prepare_files=lambda: calls.append("prepare"),
                        apply_files=lambda: None, rollback_files=lambda: None,
                        apply_unit=lambda: None, rollback_unit=lambda: None,
                        verify=lambda: None,
                    )
        self.assertEqual(calls, [])
        (self.root / "fixture-owner").unlink()
        with self.assertRaisesRegex(compose.CompositeSafetyError, "ownership marker"):
            self.run_composed()
        self.assertEqual(calls, [])
        self.assertEqual(self.installed.read_bytes(), self.old)


if __name__ == "__main__":
    unittest.main()
