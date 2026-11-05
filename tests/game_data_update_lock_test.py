#!/usr/bin/env python3
"""Advisory lock guarantees for shared game-data updates (#977)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agents.linux.runtime.game_data_update_lock import (
    GameDataUpdateLockError, game_data_update_lock,
)


class GameDataUpdateLockTests(unittest.TestCase):
    def test_same_installation_cannot_be_updated_concurrently(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "dayz-serverfiles"
            target.mkdir()
            with game_data_update_lock(target):
                with self.assertRaisesRegex(GameDataUpdateLockError, "game_data_update_busy"):
                    with game_data_update_lock(target, timeout=0):
                        self.fail("should not acquire same installation")
            with game_data_update_lock(target, timeout=0):
                pass

    def test_separate_targets_have_independent_locks(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "dayz"
            second = Path(td) / "minecraft"
            first.mkdir()
            second.mkdir()
            with game_data_update_lock(first):
                with game_data_update_lock(second, timeout=0):
                    pass

    def test_lock_survives_target_swap(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "serverfiles"
            target.mkdir()
            with game_data_update_lock(target):
                previous = Path(td) / "previous"
                os.replace(target, previous)
                target.mkdir()
                with self.assertRaisesRegex(GameDataUpdateLockError, "game_data_update_busy"):
                    with game_data_update_lock(target, timeout=0):
                        pass

    def test_symlink_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "serverfiles"
            target.mkdir()
            (Path(td) / ".serverfiles.capivara-game-data-update.lock").symlink_to("/etc/passwd")
            with self.assertRaises(GameDataUpdateLockError):
                with game_data_update_lock(target):
                    self.fail("should never follow lock symlink")

    def test_directory_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "serverfiles"
            target.mkdir()
            (Path(td) / ".serverfiles.capivara-game-data-update.lock").mkdir()
            with self.assertRaises(OSError):
                with game_data_update_lock(target):
                    self.fail("should reject a directory as a file lock")

    def test_lock_file_not_removed_on_release(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "serverfiles"
            target.mkdir()
            with game_data_update_lock(target):
                pass
            self.assertTrue((Path(td) / ".serverfiles.capivara-game-data-update.lock").is_file())

    def test_invalid_targets_and_timeouts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target"
            target.mkdir()
            link = root / "linked"
            link.symlink_to(target, target_is_directory=True)
            for bad in (Path("relative/path"), link):
                with self.assertRaises(GameDataUpdateLockError):
                    with game_data_update_lock(bad):
                        pass
            with self.assertRaises(GameDataUpdateLockError):
                with game_data_update_lock(target, timeout=-1):
                    pass


if __name__ == "__main__":
    unittest.main()
