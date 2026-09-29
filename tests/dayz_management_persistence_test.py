#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "agents" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from dayz_management import prepare_mission_persistence, restore_mission_persistence


class DayZManagementPersistenceTest(unittest.TestCase):
    def test_fresh_archives_only_exact_storage_number_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "instance"
            working = Path(temp) / "runtime"
            mission = "dayzOffline.enoch"
            mission_root = root / "mpmissions" / mission
            storage = mission_root / "storage_1"
            manual_backup = mission_root / "storage_1.backup-keep"
            (storage / "data").mkdir(parents=True)
            (storage / "data" / "types.bin").write_bytes(b"types")
            manual_backup.mkdir()
            (manual_backup / "sentinel").write_text("keep", encoding="utf-8")

            record = {
                "instance_state_root": str(root),
                "working_directory": str(working),
                "arguments": [],
            }

            preparation = prepare_mission_persistence(record, mission, "fresh")

            self.assertFalse(storage.exists())
            self.assertTrue(manual_backup.is_dir())
            self.assertEqual(1, len(preparation["archived"]))
            self.assertEqual(str(storage.resolve()), preparation["archived"][0]["original"])

            restored = restore_mission_persistence(preparation)
            self.assertEqual([str(storage.resolve())], restored["restored"])
            self.assertTrue((storage / "data" / "types.bin").is_file())
            self.assertTrue((manual_backup / "sentinel").is_file())


if __name__ == "__main__":
    unittest.main()
