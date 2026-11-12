"""Disposable read-only retention budget tests for Minecraft/DayZ (#1013)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from backup_age_retention_capacity_gate import GIB, forecast


class BackupRetentionCapacityGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm-1013-retention-budget-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "backups"
        self.root.mkdir()
        self.now = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)

    def archive(self, iid: str, size: int, age_days: float = 0):
        target = self.root / iid
        target.mkdir(exist_ok=True)
        file = target / (str(uuid4()) + ".tar.gz")
        file.write_bytes(b"x" * size)
        at = (self.now - timedelta(days=age_days)).timestamp()
        os.utime(file, (at, at))
        return file

    def test_two_games_fail_when_window_would_exhaust_root(self):
        for _ in range(3):
            self.archive("minecraft005", 12, 1)
        for _ in range(2):
            self.archive("dayz001", 15, 2)
        before = tuple(sorted(str(p) for p in self.root.rglob("*")))
        result = forecast(
            self.root, ["minecraft005", "dayz001"],
            now=self.now, available_bytes=250,
            reserve_gib=1,
        )
        self.assertEqual(result["status"], "blocked_insufficient_capacity")
        self.assertEqual(result["additional_archive_bytes"], 11*12 + 12*15)
        self.assertEqual(result["transient_slack_bytes"], 12 + 15)
        self.assertEqual(result["deficit_bytes"],
                         result["required_free_bytes"] - 250)
        self.assertEqual(before, tuple(sorted(str(p) for p in self.root.rglob("*"))))

    def test_pass_only_with_free_space_for_all_copies_and_cycle(self):
        self.archive("minecraft005", 25)
        self.archive("dayz001", 40)
        needed = 13*25 + 13*40 + 25 + 40 + GIB
        result = forecast(self.root, ["minecraft005", "dayz001"],
                          now=self.now, available_bytes=needed, reserve_gib=1)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["deficit_bytes"], 0)

    def test_age_excludes_old_archive_but_keeps_it_for_sizing(self):
        self.archive("old-instance", 90, age_days=20)
        self.archive("old-instance", 50, age_days=2)
        result = forecast(self.root, ["old-instance"],
                          now=self.now, available_bytes=100*GIB,
                          reserve_gib=1)
        self.assertEqual(result["instances"][0]["within_retention_days"], 1)
        self.assertEqual(result["instances"][0]["max_archive_bytes"], 90)
        self.assertEqual(result["additional_archive_bytes"], 13*90)

    def test_symlinked_backup_folder_or_archive_fails_closed(self):
        outside = self.archive("outside", 17)
        (self.root / "alias").symlink_to(self.root / "outside", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            forecast(self.root, ["alias"], now=self.now, available_bytes=10*GIB)
        (self.root / "another").mkdir()
        (self.root / "another" / (str(uuid4()) + ".tar.gz")).symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            forecast(self.root, ["another"], now=self.now, available_bytes=10*GIB)

    def test_missing_baseline_and_duplicate_ids_refused(self):
        (self.root / "empty").mkdir()
        with self.assertRaisesRegex(ValueError, "baseline"):
            forecast(self.root, ["empty"], now=self.now, available_bytes=10*GIB)
        self.archive("ok", 10)
        with self.assertRaisesRegex(ValueError, "unique"):
            forecast(self.root, ["ok", "ok"], now=self.now, available_bytes=10*GIB)
        for unsafe_id in ("../unsafe", ".", ".."):
            with self.subTest(instance_id=unsafe_id), self.assertRaisesRegex(ValueError, "invalid instance"):
                forecast(self.root, [unsafe_id], now=self.now, available_bytes=10*GIB)

    def test_invalid_parameters_fail_closed(self):
        self.archive("ok", 10)
        for settings in ({"days": 0}, {"copies_per_day": 0},
                         {"reserve_gib": 0}, {"safety_cycles": 0},
                         {"available_bytes": -1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                forecast(self.root, ["ok"], now=self.now, **settings)

    def test_cli_never_writes_and_returns_nonzero_on_insufficient_space(self):
        self.archive("ok", 128)
        path = ROOT / "scripts" / "backup_age_retention_capacity_gate.py"
        before = tuple(p.name for p in (self.root / "ok").iterdir())
        run = subprocess.run([sys.executable, str(path),
                              "--backup-root", str(self.root),
                              "--instance", "ok",
                              "--reserve-gib", "1000"],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn('"blocked_insufficient_capacity"', run.stdout)
        self.assertEqual(before, tuple(p.name for p in (self.root / "ok").iterdir()))


if __name__ == "__main__":
    unittest.main()
