#!/usr/bin/env python3
"""Prepared maintenance checkpoints must block overlapping DayZ updates."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.linux.runtime.prepared_game_data_guard import (
    PreparedGameDataTransactionError, reject_prepared_dayz_transaction,
)


def write_checkpoint(root: Path, target: Path, *, state="prepared", game="dayz") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "game-update-checkpoint.json"
    path.write_text(json.dumps({
        "kind": "CapivaraMaintenanceGameUpdateTransaction",
        "state": state, "game_id": game, "target": str(target),
    }))
    return path


class PreparedGameDataGuardTests(unittest.TestCase):
    def test_prepared_same_installation_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "serverfiles"
            target.mkdir()
            root = base / "state"
            write_checkpoint(root, target)
            with self.assertRaisesRegex(PreparedGameDataTransactionError, "prepared_dayz_transaction_pending"):
                reject_prepared_dayz_transaction(target, transaction_root=root)

    def test_other_installation_and_game_are_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "dayz"
            other = base / "other"
            target.mkdir()
            other.mkdir()
            root = base / "state"
            write_checkpoint(root, other)
            reject_prepared_dayz_transaction(target, transaction_root=root)
            write_checkpoint(root, target, game="minecraft")
            reject_prepared_dayz_transaction(target, transaction_root=root)

    def test_finalized_checkpoint_no_longer_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "dayz"
            target.mkdir()
            root = base / "state"
            write_checkpoint(root, target, state="committed")
            reject_prepared_dayz_transaction(target, transaction_root=root)
            write_checkpoint(root, target, state="rolled_back")
            reject_prepared_dayz_transaction(target, transaction_root=root)

    def test_invalid_checkpoint_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "dayz"
            target.mkdir()
            root = base / "state"
            root.mkdir()
            (root / "corrupt.json").write_text("invalid")
            with self.assertRaisesRegex(PreparedGameDataTransactionError, "invalid_maintenance_checkpoint"):
                reject_prepared_dayz_transaction(target, transaction_root=root)

    def test_checkpoint_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "dayz"
            target.mkdir()
            root = base / "state"
            write_checkpoint(root, target)
            (root / "other.json").symlink_to(root / "game-update-checkpoint.json")
            with self.assertRaisesRegex(PreparedGameDataTransactionError, "unsafe_maintenance_checkpoint"):
                reject_prepared_dayz_transaction(target, transaction_root=root)

    def test_no_checkpoints_allows_update(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "dayz"
            target.mkdir()
            reject_prepared_dayz_transaction(target, transaction_root=base / "missing")

    def test_both_transaction_paths_enforce_guard(self):
        root = Path(__file__).resolve().parents[1] / "agents/linux/runtime"
        normal = (root / "server_update_agent.py").read_text()
        maintenance = (root / "maintenance_game_update.py").read_text()
        self.assertIn("reject_prepared_dayz_transaction(target)", normal)
        self.assertIn("reject_prepared_dayz_transaction(target,transaction_root=TRANSACTION_ROOT)", maintenance)


if __name__ == "__main__":
    unittest.main()
