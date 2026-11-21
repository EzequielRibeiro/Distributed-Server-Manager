"""#928 Stage 2: one grouped root-journal/ephemeral-hold regression.

Disposable temporary paths only. No installed DSM, Agents, customer game
units, release pipeline or host service is modified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from game_uptime_maintenance_hold import observe
from game_uptime_hold_coordinator import (
    HoldPreparationBlocked,
    prepare_root_only,
)


class PersistentPendingHoldTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-pending-")
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.state = base / "state"
        self.run = base / "run"
        self.state.mkdir(mode=0o755)
        self.run.mkdir(mode=0o755)
        self.journal = self.state / "no-drain-pending.json"
        self.marker = self.run / "no-drain-maintenance.json"
        self.uid = os.geteuid()
        self.tx = "1" * 32

    def prepare(self, **overrides):
        kwargs = {
            "transaction_id": self.tx, "ttl_seconds": 600,
            "journal_path": self.journal, "hold_path": self.marker,
            "trusted_uid": self.uid, "now": 1700000000,
        }
        kwargs.update(overrides)
        return prepare_root_only(**kwargs)

    def observation(self):
        return observe(path=self.marker, pending_path=self.journal,
                       trusted_uid=self.uid, now=1700000010)

    def test_durable_preparation_remains_negative_and_recovers_fail_closed(self):
        # A restrictive installer/systemd umask must not make the hold 0600.
        # Its JSON contains no credentials; Agent/Worker users need read only.
        previous_umask = os.umask(0o077)
        try:
            result = self.prepare()
        finally:
            os.umask(previous_umask)
        self.assertEqual(result["status"],
                         "persistent_hold_prepared_manual_recovery_required")
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertFalse(result["remote_agents_acked"])
        journal = json.loads(self.journal.read_text())
        marker = json.loads(self.marker.read_text())
        self.assertEqual(journal["transaction_id"], marker["transaction_id"])
        self.assertEqual(journal["state"], "prepared_requires_distributed_fence")
        self.assertEqual(marker["kind"], "CapivaraDSMNoDrainMaintenanceHold")
        self.assertEqual(stat.S_IMODE(self.journal.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.marker.stat().st_mode), 0o644)
        self.assertEqual(self.marker.stat().st_uid, self.uid)
        self.assertEqual(self.journal.stat().st_uid, self.uid)
        self.assertFalse(self.marker.stat().st_mode & 0o022)
        with os.fdopen(os.open(self.marker, os.O_RDONLY | os.O_NOFOLLOW), "r") as stream:
            self.assertEqual(json.load(stream)["transaction_id"], self.tx)
        self.assertEqual(self.observation()["reason"], "root_owned_maintenance_hold")

        # Model a process crash/reboot removing only the /run marker. The
        # persistent pending inode MUST still block the next Worker tick.
        self.marker.unlink()
        self.assertEqual(self.observation(),
                         {"active": True,
                          "reason": "pending_journal_requires_operator_recovery"})
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare()  # Never overwrite/replay without manual recovery.

    def test_partial_journal_blocks_after_crash_before_marker_write(self):
        self.journal.write_bytes(b"{incomplete")
        self.journal.chmod(0o600)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.observation()["reason"],
                         "pending_journal_requires_operator_recovery")

    def test_invalid_lease_and_transaction_never_create_files(self):
        for changes in (
            {"transaction_id": "../bad"},
            {"transaction_id": "f" * 31},
            {"ttl_seconds": 0},
            {"ttl_seconds": 901},
            {"ttl_seconds": True},
            {"now": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(HoldPreparationBlocked):
                self.prepare(**changes)
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.marker.exists())

    def test_symlink_or_writable_parent_cannot_start_transaction(self):
        external = self.state / "outside"
        external.write_text("do not overwrite")
        self.journal.symlink_to(external)
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare()
        self.assertEqual(external.read_text(), "do not overwrite")
        self.assertFalse(self.marker.exists())
        self.journal.unlink()
        self.state.chmod(0o777)
        try:
            with self.assertRaises(HoldPreparationBlocked):
                self.prepare()
            self.assertFalse(self.journal.exists())
        finally:
            self.state.chmod(0o755)

    def test_hold_write_collision_keeps_existing_evidence_and_pending_block(self):
        self.marker.write_text("protected marker")
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare()
        self.assertEqual(self.marker.read_text(), "protected marker")
        self.assertTrue(self.journal.exists())
        # Invalid marker already blocks. After marker loss, pending still blocks.
        self.marker.unlink()
        self.assertTrue(self.observation()["active"])


if __name__ == "__main__":
    unittest.main()
