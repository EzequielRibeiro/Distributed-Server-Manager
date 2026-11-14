"""#928: disposable updater file functions and systemd swap in one transaction.

This unit test suite uses a fake systemd reload, exact /tmp fixture marker
and fake PIDs only. A separate root/systemd E2E tests real transient units.
"""
from __future__ import annotations

import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import json
import os
import signal
import subprocess
import sys
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

    def run_gated(self, *, controller=None, agent=None, pinned=True):
        contract = {"protocol": "v1", "schema": "22",
                    "controller_api": "v2", "agent_api": "v2"}
        return compose.execute_with_compatibility_gate(
            self.root, [UNIT, DAYZ],
            controller_contract=contract if controller is None else controller,
            agent_contract=contract if agent is None else agent,
            supervisor_pinned_preview=pinned,
            inspect=self.inspect,
            prepare_files=lambda: self.updater("prepare"),
            apply_files=lambda: self.updater("apply"),
            rollback_files=lambda: self.updater("rollback"),
            apply_unit=self.swap_unit,
            rollback_unit=self.restore_unit,
            verify=self.verify,
        )

    def set_fixture_supervisors(self, *, installed="stable", candidate="stable"):
        relative = "agents/linux/runtime/console_supervisor.py"
        for base, source in ((self.root/"installed", installed),
                             (self.root/"new-payload", candidate)):
            if source is None:
                continue
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        return relative

    def test_composite_gate_accepts_explicit_matching_synthetic_contract(self):
        self.set_fixture_supervisors()
        receipt = self.run_gated()
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(receipt["compatibility_source"], "synthetic_disposable_fixture")
        self.assertTrue(receipt["controller_agent_contract_compatible"])
        self.assertFalse(receipt["live_no_drain_authorized"])
        self.assertEqual(self.states[UNIT]["pid"], 22001)
        self.assertEqual(self.states[DAYZ]["pid"], 22002)
        self.assertEqual(self.installed.read_bytes(), self.new)
        self.restore_unit()
        self.updater("rollback")

    def test_composite_gate_blocks_mismatch_before_any_update_or_snapshot(self):
        self.set_fixture_supervisors()
        wrong = {"protocol": "v1", "schema": "23",
                 "controller_api": "v2", "agent_api": "v2"}
        with self.assertRaisesRegex(compose.CompositeSafetyError, "schema_mismatch"):
            self.run_gated(agent=wrong)
        self.assertFalse((self.root/"backups").exists())
        self.assertFalse((self.root/"dsm928-composite-journal").exists())
        self.assertEqual(self.installed.read_bytes(), self.old)

    def test_composite_gate_allows_changed_supervisor_only_with_pinned_preview(self):
        self.set_fixture_supervisors(installed="old", candidate="new")
        with self.assertRaisesRegex(compose.CompositeSafetyError,
                                    "minecraft_live_supervisor_replaceable"):
            self.run_gated(pinned=False)
        self.assertFalse((self.root/"backups").exists())
        receipt = self.run_gated(pinned=True)
        self.assertEqual(receipt["status"], "verified")
        self.assertFalse(receipt["live_no_drain_authorized"])
        self.restore_unit()
        self.updater("rollback")
        self.assertEqual(self.installed.read_bytes(), self.old)

    def test_composite_gate_rejects_unpinned_even_with_matching_bytes(self):
        self.set_fixture_supervisors()
        with self.assertRaisesRegex(compose.CompositeSafetyError,
                                    "supervisor_lifecycle_not_isolated"):
            self.run_gated(pinned=False)
        self.assertFalse((self.root/"backups").exists())

    def test_composite_gate_rejects_missing_or_unverifiable_supervisor(self):
        self.set_fixture_supervisors(candidate=None)
        with self.assertRaisesRegex(compose.CompositeSafetyError,
                                    "minecraft_supervisor_unverifiable"):
            self.run_gated()
        self.assertFalse((self.root/"backups").exists())

    def test_composite_gate_rejects_missing_contract_before_callbacks(self):
        self.set_fixture_supervisors()
        with self.assertRaisesRegex(compose.CompositeSafetyError,
                                    "controller_agent_.*mismatch"):
            self.run_gated(controller={})
        self.assertFalse((self.root/"backups").exists())

    def test_composite_gate_requires_disposable_owner_marker(self):
        self.set_fixture_supervisors()
        (self.root/"fixture-owner").unlink()
        with self.assertRaisesRegex(compose.CompositeSafetyError,
                                    "ownership marker"):
            self.run_gated()
        self.assertFalse((self.root/"backups").exists())

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


    def recover(self, **overrides):
        kw = dict(
            inspect=self.inspect,
            rollback_files=lambda: self.updater("rollback"),
            rollback_unit=self.restore_unit,
            verify=self.verify, operator_reviewed=True,
        )
        kw.update(overrides)
        return compose.recover_interrupted(self.root, [UNIT, DAYZ], **kw)

    @unittest.skipUnless(os.name == "posix" and hasattr(signal, "SIGKILL"),
                         "real SIGKILL requires POSIX")
    def test_real_sigkill_after_both_components_needs_reviewed_dual_recovery(self):
        """SIGKILL subprocess after a real fixture file apply and unit swap."""
        script = r"""
import hashlib, importlib.util, os, signal, sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "tests"))
from update_game_uptime_real_update_functions_test import run_real_update_fns
root = Path(sys.argv[2])
unit = "dsm928-e2e-minecraft-pinned.service"
dayz = "dsm928-e2e-dayz-sim.service"
def load(path,name):
    loader=SourceFileLoader(name,str(Path(sys.argv[1])/path))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    mod=importlib.util.module_from_spec(spec);loader.exec_module(mod)
    return mod
compose=load("update-manager/game-uptime-isolated-compose.py","dsm928_child_composite")
swap=load("update-manager/game-uptime-systemd-swap.py","dsm928_child_swap")
states={unit:{"unit":unit,"state":"active","pid":22001,"started":901},
        dayz:{"unit":dayz,"state":"active","pid":22002,"started":902}}
def upd(phase):
    x=run_real_update_fns(root,phase)
    if x.returncode:raise RuntimeError(x.stderr)
def unit_apply():
    old=(root/"units"/unit).read_bytes()
    new=("# DSM928_DISPOSABLE_UNIT_V1\n# DSM928_UNIT="+unit+
         "\n[Unit]\nDescription=DSM928 isolated unit transaction\n"
         "[Service]\nType=simple\nExecStart=/usr/bin/sleep 170\n").encode()
    swap.swap_unit(root,unit,unit_dir=root/"units",candidate=new,
                   expected_old_sha256=hashlib.sha256(old).hexdigest(),
                   inspect=lambda n:states[n],runner=lambda:True)
    os.kill(os.getpid(),signal.SIGKILL)
compose.execute(root,[unit,dayz],
    inspect=lambda n:states[n],
    prepare_files=lambda:upd("prepare"),
    apply_files=lambda:upd("apply"),
    rollback_files=lambda:upd("rollback"),
    apply_unit=unit_apply,
    rollback_unit=lambda:None,
    verify=lambda:None)
"""
        child = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(self.root)],
            check=False, capture_output=True, text=True, timeout=25,
        )
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr[-1200:])
        self.assertEqual(self.installed.read_bytes(), self.new)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.999-fixture")
        journal = self.root / "dsm928-composite-journal/game-uptime-transaction.json"
        self.assertEqual(json.loads(journal.read_text())["status"], "prepared")
        self.assertEqual(
            json.loads((self.root / "dsm928-unit-swap.json").read_text())["status"],
            "applied")
        with self.assertRaisesRegex(compose.CompositeSafetyError, "operator review"):
            self.recover(operator_reviewed=False)
        with self.assertRaisesRegex(compose.CompositeSafetyError, "existing composite"):
            self.run_composed()
        self.assertEqual(self.installed.read_bytes(), self.new)
        recovered = self.recover()
        self.assertEqual(recovered["status"], "recovered_rollback")
        self.assertFalse(recovered["live_no_drain_authorized"])
        self.assertEqual(self.installed.read_bytes(), self.old)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual(json.loads(journal.read_text())["status"],
                         "recovered_rollback")
        self.assertEqual(
            json.loads((self.root / "dsm928-unit-swap.json").read_text())["status"],
            "restored")
        with self.assertRaisesRegex(compose._TRANSACTION.TransactionSafetyError,
                                    "recoverable interruption"):
            self.recover()

    def test_crash_before_unit_component_recovers_only_file_fixture(self):
        def abort_before_swap():
            raise SystemExit(41)
        with self.assertRaises(SystemExit):
            self.run_composed(apply_unit=abort_before_swap)
        self.assertFalse((self.root / "dsm928-unit-swap.json").exists())
        outcome = self.recover()
        self.assertEqual(outcome["status"], "recovered_rollback")
        self.assertEqual(self.reloads, 0)
        self.assertEqual(self.installed.read_bytes(), self.old)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")

    def test_changed_pid_prevents_any_composite_recovery_action(self):
        def abort_after_swap():
            self.swap_unit()
            raise SystemExit(41)
        with self.assertRaises(SystemExit):
            self.run_composed(apply_unit=abort_after_swap)
        self.states[UNIT]["pid"] += 1
        calls = []
        with self.assertRaisesRegex(compose._TRANSACTION.TransactionSafetyError,
                                    "process identity changed"):
            self.recover(
                rollback_unit=lambda: calls.append("unit"),
                rollback_files=lambda: calls.append("files"),
            )
        self.assertEqual(calls, [])
        self.assertEqual(self.installed.read_bytes(), self.new)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.999-fixture")

    def test_corrupt_unit_journal_refuses_composite_recovery(self):
        def abort_after_swap():
            self.swap_unit()
            raise SystemExit(41)
        with self.assertRaises(SystemExit):
            self.run_composed(apply_unit=abort_after_swap)
        path = self.root / "dsm928-unit-swap.json"
        path.write_text("{unreadable")
        with self.assertRaisesRegex(compose.CompositeSafetyError,
                                    "unreadable disposable unit"):
            self.recover(
                rollback_unit=lambda: self.fail("wrong component rollback"),
                rollback_files=lambda: self.fail("wrong file rollback"),
            )
        self.assertEqual(self.installed.read_bytes(), self.new)
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.999-fixture")

    def test_recovery_partial_failure_preserves_manual_gate(self):
        def abort_after_swap():
            self.swap_unit()
            raise SystemExit(41)
        with self.assertRaises(SystemExit):
            self.run_composed(apply_unit=abort_after_swap)
        with self.assertRaisesRegex(compose._TRANSACTION.TransactionSafetyError,
                                    "manual review required"):
            self.recover(
                rollback_unit=lambda: (_ for _ in ()).throw(
                    RuntimeError("unit rollback deliberately failed")),
            )
        self.assertEqual(
            (self.root / "installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual(self.installed.read_bytes(), self.new)
        journal = self.root / "dsm928-composite-journal/game-uptime-transaction.json"
        self.assertEqual(json.loads(journal.read_text())["status"],
                         "manual_recovery_required")
        with self.assertRaisesRegex(compose._TRANSACTION.TransactionSafetyError,
                                    "recoverable interruption"):
            self.recover()



if __name__ == "__main__":
    unittest.main()
