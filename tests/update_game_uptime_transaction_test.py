"""Fail-closed disposable uptime transaction tests; no production updater."""
from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader(
    "dsm928_transaction", str(ROOT/"update-manager/game-uptime-transaction.py")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
tx = importlib.util.module_from_spec(spec)
loader.exec_module(tx)


class DisposableUptimeTransactionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dsm928-transaction-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.units = [
            "dsm928-e2e-unit-alpha.service",
            "dsm928-e2e-unit-beta.service",
        ]
        self.snapshots = {
            name: {"unit": name, "pid": 2000 + idx, "started": 3000 + idx, "state": "active"}
            for idx, name in enumerate(self.units)
        }
        self.value = "before"
        self.undo_count = 0
        self.apply_count = 0

    def inspect(self, name):
        return dict(self.snapshots[name])

    def apply(self):
        self.apply_count += 1
        self.value = "after"

    def rollback(self):
        self.undo_count += 1
        self.value = "before"

    def run_tx(self, **kwargs):
        options = {
            "inspect": self.inspect, "apply": self.apply, "rollback": self.rollback,
        }
        options.update(kwargs)
        return tx.execute(self.root, self.units, **options)

    def journal(self):
        return json.loads((self.root/"game-uptime-transaction.json").read_text())

    def test_success_preserves_two_pids_with_durable_receipt(self):
        outcome = self.run_tx()
        self.assertEqual(outcome["status"], "verified")
        self.assertFalse(outcome["live_no_drain_authorized"])
        self.assertEqual(len(outcome["units"]), 2)
        self.assertEqual(self.value, "after")
        self.assertEqual(self.undo_count, 0)
        self.assertEqual(self.journal()["status"], "verified")

    def test_apply_failure_rolls_back_and_keeps_original_identity(self):
        def fail():
            self.apply()
            raise RuntimeError("injected failure after file replacement")
        with self.assertRaisesRegex(tx.TransactionSafetyError, "rollback completed"):
            self.run_tx(apply=fail)
        self.assertEqual(self.value, "before")
        self.assertEqual(self.undo_count, 1)
        self.assertEqual(self.journal()["status"], "rolled_back")

    def test_pid_change_triggers_rollback_but_requires_manual_recovery(self):
        def restarted():
            self.apply()
            self.snapshots[self.units[1]]["pid"] = 8000
        with self.assertRaisesRegex(tx.TransactionSafetyError, "manual recovery"):
            self.run_tx(apply=restarted)
        self.assertEqual(self.undo_count, 1)
        self.assertEqual(self.value, "before")
        self.assertEqual(self.journal()["status"], "manual_recovery_required")

    def test_rollback_failure_is_explicit_and_keeps_journal(self):
        def fail():
            self.apply()
            raise RuntimeError("apply fail")
        def undo_fail():
            raise RuntimeError("rollback could not restore")
        with self.assertRaisesRegex(tx.TransactionSafetyError, "manual recovery"):
            self.run_tx(apply=fail, rollback=undo_fail)
        self.assertEqual(self.journal()["status"], "manual_recovery_required")
        self.assertEqual(self.value, "after")

    def test_abrupt_termination_leaves_prepared_receipt_and_blocks_replay(self):
        def crash():
            self.apply()
            raise SystemExit(42)
        with self.assertRaises(SystemExit):
            self.run_tx(apply=crash)
        self.assertEqual(self.journal()["status"], "prepared")
        with self.assertRaisesRegex(tx.TransactionSafetyError, "existing transaction"):
            self.run_tx()
        self.assertEqual(self.apply_count, 1)

    def test_unknown_process_and_duplicate_units_fail_before_apply(self):
        for bad in (
            ["capivara-instance-customer.service"],
            ["dsm928-e2e-unit-alpha.service", "dsm928-e2e-unit-alpha.service"],
            [["not-a-hashable-unit"]],
            [],
        ):
            with self.subTest(units=bad):
                with self.assertRaises(tx.TransactionSafetyError):
                    tx.execute(self.root, bad, inspect=self.inspect,
                               apply=self.apply, rollback=self.rollback)
                self.assertEqual(self.apply_count, 0)
        self.assertFalse((self.root/"game-uptime-transaction.json").exists())

    def test_unverifiable_snapshot_fails_before_apply(self):
        self.snapshots[self.units[0]]["started"] = 0
        with self.assertRaisesRegex(tx.TransactionSafetyError, "cannot prove"):
            self.run_tx()
        self.assertEqual(self.apply_count, 0)
        self.assertFalse((self.root/"game-uptime-transaction.json").exists())

    def test_existing_symlink_journal_refuses_without_mutation(self):
        journal = self.root/"game-uptime-transaction.json"
        journal.symlink_to(self.root/"does-not-exist")
        with self.assertRaisesRegex(tx.TransactionSafetyError, "existing transaction"):
            self.run_tx()
        self.assertEqual(self.apply_count, 0)

    def test_workspace_outside_tmp_or_symlink_denied(self):
        with self.assertRaisesRegex(tx.TransactionSafetyError, "temporary sandbox"):
            tx.execute(Path("/"), self.units, inspect=self.inspect,
                       apply=self.apply, rollback=self.rollback)
        alias = self.root.with_name(self.root.name + "-alias")
        alias.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(alias.unlink)
        with self.assertRaisesRegex(tx.TransactionSafetyError, "non-symlink"):
            tx.execute(alias, self.units, inspect=self.inspect,
                       apply=self.apply, rollback=self.rollback)
        self.assertEqual(self.apply_count, 0)


if __name__ == "__main__":
    unittest.main()
