#!/usr/bin/env python3
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
MANAGER = DATABASE / "manager.py"
GUARD = ROOT / "update-manager" / "process-guard.sh"
OLD_2062_CHECKSUM = "b8d7de4a314faf5086bf02bcbc626dbbef94ba1a84eb2490f068cbb74c7634ce"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))
from baseline_upgrade_engine import latest_upgrade_version


class BaselineV12ContentUpdateTest(unittest.TestCase):
    def manager(self, root: Path, db: Path, command: str):
        return subprocess.run(
            [sys.executable, str(MANAGER), "--root", str(root), "--driver", "sqlite", "--database", str(db), command],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

    def v11_database(self, root: Path, db: Path) -> None:
        initialized = self.manager(root, db, "init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        with sqlite3.connect(db) as connection:
            connection.execute("DELETE FROM baseline_upgrades WHERE version=12")
            connection.execute("DROP TABLE content_update_state")
            connection.execute("DROP TABLE content_update_policy")
            connection.execute("UPDATE schema_baseline SET checksum=? WHERE singleton=1", (OLD_2062_CHECKSUM,))
            connection.commit()

    def test_2062_v11_database_advances_to_v12(self) -> None:
        self.assertEqual(latest_upgrade_version(), 12)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            db = root / "data" / "capivara.db"
            db.parent.mkdir(parents=True)
            self.v11_database(root, db)
            before = self.manager(root, db, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            payload = json.loads(before.stdout)
            self.assertEqual(payload["upgrade_version"], 11)
            self.assertEqual(payload["upgrade_latest"], 12)
            self.assertEqual(payload["pending_upgrades"], [{"version": 12, "name": "universal_content_update"}])
            migrated = self.manager(root, db, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            payload = json.loads(migrated.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["upgrade_version"], 12)
            with sqlite3.connect(db) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertTrue({"content_update_policy", "content_update_state"} <= tables)
            self.assertTrue({"idx_content_update_state_instance", "idx_content_update_state_agent"} <= indexes)

    def test_guard_rejects_checksum_mismatch_without_pending_upgrade(self) -> None:
        payload = {
            "schema_version": 2, "kind": "DatabaseCheck", "driver": "postgresql",
            "connected": True, "initialized": True, "health": "error",
            "baseline": "capivara-baseline-v2", "baseline_checksum": OLD_2062_CHECKSUM,
            "expected_baseline": "capivara-baseline-v2", "expected_checksum": "target-checksum",
            "checksum_matches": False, "missing_tables": [], "upgrade_ledger": True,
            "upgrade_version": 11, "upgrade_latest": 11, "pending_upgrades": [],
            "upgrade_error": None, "valid": False,
        }
        script = f'source "{GUARD}"; process_guard_database_check_is_upgradeable "$PAYLOAD" "{ROOT}"'
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env={**__import__("os").environ, "PAYLOAD": json.dumps(payload)}, text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_release_builder_does_not_weaken_process_guard(self) -> None:
        text = (ROOT / "release" / "build_release.sh").read_text(encoding="utf-8")
        self.assertNotIn("fully reconciled ledger is already compatible", text)
        self.assertNotIn("Baseline v2 preflight hotfix anchor", text)


if __name__ == "__main__":
    unittest.main()
