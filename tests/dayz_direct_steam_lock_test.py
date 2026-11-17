#!/usr/bin/env python3
"""Direct DayZ Steam installs must not bypass game-data serialization."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
import game_data_executor as executor
from game_data_update_lock import GameDataUpdateLockError, game_data_update_lock
from prepared_game_data_guard import PreparedGameDataTransactionError


class DayZDirectSteamLockTest(unittest.TestCase):
    def fixture(self, directory):
        root=Path(directory)/"game-data"
        target=root/"dayz"/"serverfiles"
        target.parent.mkdir(parents=True)
        target.mkdir()
        return root,target

    def test_direct_install_blocks_when_same_installation_is_locked(self):
        with tempfile.TemporaryDirectory() as td:
            root,target=self.fixture(td)
            selection={"game":"dayz","provider":"steam","install_dir":"serverfiles"}
            with patch.object(executor,"GAME_DATA_ROOT",root), patch.object(
                    executor,"_execute_without_direct_game_data_lock") as inner:
                with game_data_update_lock(target):
                    with self.assertRaisesRegex(GameDataUpdateLockError,"game_data_update_busy"):
                        executor._execute({"action":"install","selection":selection})
                inner.assert_not_called()

    def test_direct_ensure_and_repair_use_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root,target=self.fixture(td)
            for action in ("ensure","repair","update"):
                selection={"game":"dayz","provider":"steam","install_dir":"serverfiles"}
                with patch.object(executor,"GAME_DATA_ROOT",root), patch.object(
                        executor,"_execute_without_direct_game_data_lock",return_value={"ok":True}) as inner:
                    self.assertEqual(executor._execute({"action":action,"selection":selection}),{"ok":True})
                    inner.assert_called_once()

    def test_pending_maintenance_blocks_direct_install(self):
        with tempfile.TemporaryDirectory() as td:
            root,target=self.fixture(td)
            state=Path(td)/"server-update-maintenance"
            state.mkdir()
            (state/"checkpoint.json").write_text(json.dumps({
                "kind":"CapivaraMaintenanceGameUpdateTransaction",
                "state":"prepared","game_id":"dayz","target":str(target)
            }))
            selection={"game":"dayz","provider":"steam","install_dir":"serverfiles"}
            with patch.object(executor,"GAME_DATA_ROOT",root), patch.dict(
                    "os.environ",{"CAPIVARA_AGENT_STATE_DIR":str(td)}), patch.object(
                    executor,"_execute_without_direct_game_data_lock") as inner:
                with self.assertRaisesRegex(PreparedGameDataTransactionError,"prepared_dayz_transaction_pending"):
                    executor._execute({"action":"install","selection":selection})
                inner.assert_not_called()

    def test_scoped_direct_install_and_repair_rejected(self):
        for action in ("install","ensure","repair"):
            selection={"game":"dayz","provider":"steam",
                       "_server_update":{"instance_id":"dayz-one","operation":"update"}}
            with patch.object(executor,"_execute_without_direct_game_data_lock") as inner:
                with self.assertRaisesRegex(RuntimeError,"transactional update"):
                    executor._execute({"action":action,"selection":selection})
                inner.assert_not_called()

    def test_non_dayz_does_not_use_new_gate(self):
        with patch.object(executor,"_execute_without_direct_game_data_lock",return_value={"other":True}) as inner:
            self.assertEqual(executor._execute({"action":"install","selection":{"game":"minecraft"}}),{"other":True})
            inner.assert_called_once()


if __name__=="__main__":
    unittest.main()
