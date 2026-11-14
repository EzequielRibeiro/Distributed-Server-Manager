"""Disposable systemd file swap: no production units or real systemctl here."""
from __future__ import annotations

import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader(
    "dsm928_disposable_swap_unit",
    str(ROOT / "update-manager/game-uptime-systemd-swap.py"),
)
spec = importlib.util.spec_from_loader(loader.name, loader)
swap = importlib.util.module_from_spec(spec)
loader.exec_module(swap)


def unit_content(name: str, seconds: int = 180) -> bytes:
    return (
        f"# DSM928_DISPOSABLE_UNIT_V1\n"
        f"# DSM928_UNIT={name}\n"
        "[Unit]\nDescription=DSM928 disposable test only\n"
        "[Service]\nType=simple\n"
        f"ExecStart=/usr/bin/sleep {seconds}\n"
    ).encode("utf-8")


class DisposableSystemdUnitSwapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm928-unit-swap-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.units = self.root / "units"
        self.units.mkdir()
        # The fake unit directory must be a child of the same private sandbox
        # that owns the transaction journal; never accept sibling roots.
        self.journal = self.root
        self.unit = "dsm928-e2e-swap-fixture.service"
        self.file = self.units / self.unit
        self.old = unit_content(self.unit, 180)
        self.new = unit_content(self.unit, 170)
        self.file.write_bytes(self.old)
        self.original = {"unit": self.unit, "state": "active",
                         "pid": 13131, "started": 123456}
        self.snapshot = dict(self.original)
        self.reloads = 0

    def inspect(self, name):
        self.assertEqual(name, self.unit)
        return dict(self.snapshot)

    def reload(self):
        self.reloads += 1
        return True

    def apply(self, **kwargs):
        return swap.swap_unit(
            self.journal, self.unit, unit_dir=self.units,
            candidate=self.new, expected_old_sha256=hashlib.sha256(self.old).hexdigest(),
            inspect=self.inspect, runner=self.reload, **kwargs,
        )

    def restore(self, **kwargs):
        return swap.restore_unit(
            self.journal, self.unit, unit_dir=self.units,
            inspect=self.inspect, runner=self.reload,
            operator_reviewed=True, **kwargs,
        )

    def record(self):
        return json.loads((self.journal / "dsm928-unit-swap.json").read_text())

    def test_unit_file_changes_and_restores_without_touching_process(self):
        first = self.apply()
        self.assertEqual(first["status"], "applied")
        self.assertFalse(first["live_no_drain_authorized"])
        self.assertEqual(self.file.read_bytes(), self.new)
        self.assertEqual(self.snapshot, self.original)
        self.assertEqual(self.reloads, 1)
        self.assertEqual(self.record()["old_sha256"],
                         hashlib.sha256(self.old).hexdigest())
        with self.assertRaisesRegex(swap.DisposableSwapError, "existing unit transaction"):
            self.apply()
        with self.assertRaisesRegex(swap.DisposableSwapError, "operator review"):
            swap.restore_unit(
                self.journal, self.unit, unit_dir=self.units,
                inspect=self.inspect, runner=self.reload)
        result = self.restore()
        self.assertEqual(result["status"], "restored")
        self.assertEqual(self.file.read_bytes(), self.old)
        self.assertEqual(self.reloads, 2)
        with self.assertRaisesRegex(swap.DisposableSwapError, "not a recoverable"):
            self.restore()

    def test_reload_failure_automatically_rolls_back_and_records(self):
        calls = {"value": 0}

        def fail_once():
            calls["value"] += 1
            return calls["value"] != 1

        with self.assertRaisesRegex(swap.DisposableSwapError, "rollback completed"):
            swap.swap_unit(
                self.journal, self.unit, unit_dir=self.units,
                candidate=self.new, expected_old_sha256=hashlib.sha256(self.old).hexdigest(),
                inspect=self.inspect, runner=fail_once)
        self.assertEqual(calls["value"], 2)
        self.assertEqual(self.file.read_bytes(), self.old)
        self.assertEqual(self.record()["status"], "rolled_back")
        self.assertFalse(self.record()["live_no_drain_authorized"])

    def test_interruption_requires_explicit_review_and_never_replays(self):
        with mock.patch.object(swap, "_reload", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.apply()
        self.assertEqual(self.file.read_bytes(), self.new)
        self.assertEqual(self.record()["status"], "prepared")
        self.assertEqual(self.restore()["status"], "restored")
        self.assertEqual(self.file.read_bytes(), self.old)
        with self.assertRaises(swap.DisposableSwapError):
            self.restore()

    def test_changed_pid_refuses_restore_and_keeps_new_unit(self):
        self.apply()
        self.snapshot["pid"] += 1
        with self.assertRaisesRegex(swap.DisposableSwapError, "process changed"):
            self.restore()
        self.assertEqual(self.file.read_bytes(), self.new)
        self.assertEqual(self.record()["status"], "applied")

    def test_foreign_name_symlink_and_stale_digest_refused(self):
        for bad in ("capivara-instance-minecraft-005.service",
                    "dsm-dashboard.service", "../escape.service"):
            with self.subTest(name=bad):
                with self.assertRaisesRegex(swap.DisposableSwapError, "only dsm928"):
                    swap.swap_unit(
                        self.journal, bad, unit_dir=self.units, candidate=self.new,
                        expected_old_sha256=hashlib.sha256(self.old).hexdigest(),
                        inspect=self.inspect, runner=self.reload)
        with self.assertRaisesRegex(swap.DisposableSwapError, "stale unit baseline"):
            swap.swap_unit(
                self.journal, self.unit, unit_dir=self.units,
                candidate=self.new, expected_old_sha256="0" * 64,
                inspect=self.inspect, runner=self.reload)
        self.assertEqual(self.reloads, 0)
        self.file.unlink()
        self.file.symlink_to(self.root / "other")
        with self.assertRaisesRegex(swap.DisposableSwapError, "symlinked"):
            self.apply()

    def test_unsafe_candidate_and_unmarked_unit_are_rejected(self):
        self.new = self.new.replace(b"/usr/bin/sleep 170", b"/usr/bin/sh -c stop-all")
        with self.assertRaisesRegex(swap.DisposableSwapError, "allowlisted"):
            self.apply()
        self.assertEqual(self.reloads, 0)
        self.file.write_bytes(self.old.replace(
            b"# DSM928_DISPOSABLE_UNIT_V1", b"# ordinary service"))
        self.new = unit_content(self.unit, 170)
        with self.assertRaisesRegex(swap.DisposableSwapError, "not marked"):
            self.apply()

    def test_corrupt_backup_and_modified_unit_deny_manual_restore(self):
        self.apply()
        backup = self.journal / "dsm928-unit-old.backup"
        backup.write_bytes(b"wrong backup data")
        with self.assertRaises(swap.DisposableSwapError):
            self.restore()
        backup.write_bytes(self.old)
        self.file.write_bytes(unit_content(self.unit, 140))
        with self.assertRaisesRegex(swap.DisposableSwapError, "changed since swap"):
            self.restore()
        self.assertEqual(self.record()["status"], "applied")

    def test_recovery_failure_is_nonreplayable(self):
        self.apply()
        with self.assertRaisesRegex(swap.DisposableSwapError, "manual review required"):
            swap.restore_unit(
                self.journal, self.unit, unit_dir=self.units,
                inspect=self.inspect, runner=lambda: False,
                operator_reviewed=True)
        self.assertEqual(self.record()["status"], "manual_recovery_required")
        with self.assertRaisesRegex(swap.DisposableSwapError, "not a recoverable"):
            self.restore()


if __name__ == "__main__":
    unittest.main()
