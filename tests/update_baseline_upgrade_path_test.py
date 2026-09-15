#!/usr/bin/env python3
"""Regression coverage for release update -> Baseline v2 reconciliation."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "database" / "manager.py"
PROCESS_GUARD = ROOT / "update-manager" / "process-guard.sh"
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))
from baseline_upgrade_engine import UPGRADES, latest_upgrade_version


class BaselineUpdatePathTest(unittest.TestCase):
    def manager(self, root: Path, database: Path, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(MANAGER),
                "--root",
                str(root),
                "--driver",
                "sqlite",
                "--database",
                str(database),
                command,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_migrate_reconciles_current_baseline_without_upgrade_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DROP TABLE baseline_upgrades")
                connection.commit()

            before = self.manager(root, database, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            before_payload = json.loads(before.stdout)
            self.assertTrue(before_payload["checksum_matches"])
            self.assertFalse(before_payload["upgrade_ledger"])
            self.assertTrue(before_payload["pending_upgrades"])
            self.assertFalse(before_payload["valid"])

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertEqual(migrated_payload["health"], "ok")
            self.assertEqual(
                migrated_payload["upgrade_version"],
                migrated_payload["upgrade_latest"],
            )

            after = self.manager(root, database, "check")
            self.assertEqual(after.returncode, 0, after.stderr)
            after_payload = json.loads(after.stdout)
            self.assertTrue(after_payload["valid"])
            self.assertTrue(after_payload["upgrade_ledger"])
            self.assertFalse(after_payload["pending_upgrades"])

    def test_migrate_repairs_missing_activity_audit_before_seeding_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DROP TABLE baseline_upgrades")
                connection.execute("DROP TABLE activity_audit")
                connection.commit()

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            payload = json.loads(migrated.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["upgrade_version"], latest_upgrade_version())
            self.assertEqual(payload["upgrade_latest"], latest_upgrade_version())

            with sqlite3.connect(database) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades ORDER BY version"
                ).fetchall()

            self.assertIn("activity_audit", tables)
            self.assertEqual(
                ledger,
                [(upgrade.version, upgrade.name) for upgrade in UPGRADES],
            )

    def test_migrate_advances_v10_datacenter_geography_to_v11(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version=11")
                for column in ("state_name", "state_code", "country_name"):
                    connection.execute(f"ALTER TABLE datacenters DROP COLUMN {column}")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",
                    ("v10-checksum-simulation",),
                )
                connection.commit()

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            payload = json.loads(migrated.stdout)
            self.assertEqual(payload["upgrade_version"], 11)
            self.assertEqual(payload["upgrade_latest"], 11)
            self.assertTrue(payload["valid"])

            with sqlite3.connect(database) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info('datacenters')")
                }
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version=11"
                ).fetchone()

            self.assertTrue({"country_name", "state_code", "state_name"} <= columns)
            self.assertEqual(ledger, (11, "datacenter_geography_metadata"))

    def guard_classifier(self, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        script = f'''\
source "{PROCESS_GUARD}"
process_guard_database_check_is_upgradeable "$PAYLOAD" "{ROOT}"
'''
        return subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            env={**__import__("os").environ, "PAYLOAD": json.dumps(payload)},
            text=True,
            capture_output=True,
            check=False,
        )

    def test_process_guard_accepts_current_baseline_pending_ledger_reconciliation(self) -> None:
        payload = {
            "schema_version": 2,
            "kind": "DatabaseCheck",
            "driver": "postgresql",
            "connected": True,
            "initialized": True,
            "health": "error",
            "baseline": "capivara-baseline-v2",
            "baseline_checksum": "current",
            "expected_baseline": "capivara-baseline-v2",
            "expected_checksum": "current",
            "checksum_matches": True,
            "missing_tables": [],
            "upgrade_ledger": False,
            "upgrade_version": 0,
            "upgrade_latest": latest_upgrade_version(),
            "pending_upgrades": [
                {"version": upgrade.version, "name": upgrade.name} for upgrade in UPGRADES
            ],
            "upgrade_error": None,
            "valid": False,
        }
        result = self.guard_classifier(payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_process_guard_rejects_unknown_preledger_checksum(self) -> None:
        payload = {
            "schema_version": 2,
            "kind": "DatabaseCheck",
            "driver": "postgresql",
            "connected": True,
            "initialized": True,
            "health": "error",
            "baseline": "capivara-baseline-v2",
            "baseline_checksum": "unknown-preledger-checksum",
            "expected_baseline": "capivara-baseline-v2",
            "expected_checksum": "current",
            "checksum_matches": False,
            "missing_tables": [],
            "upgrade_ledger": False,
            "upgrade_version": 0,
            "upgrade_latest": latest_upgrade_version(),
            "pending_upgrades": [
                {"version": upgrade.version, "name": upgrade.name} for upgrade in UPGRADES
            ],
            "upgrade_error": None,
            "valid": False,
        }
        result = self.guard_classifier(payload)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
