#!/usr/bin/env python3
"""Regression coverage for release update -> Baseline v2 reconciliation."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "database" / "manager.py"
PROCESS_GUARD = ROOT / "update-manager" / "process-guard.sh"


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
            self.assertEqual(payload["upgrade_version"], 3)
            self.assertEqual(payload["upgrade_latest"], 3)

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
                [
                    (1, "discord_integration"),
                    (2, "agent_public_network"),
                    (3, "activity_audit"),
                ],
            )

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
            "upgrade_latest": 3,
            "pending_upgrades": [
                {"version": 1, "name": "discord_integration"},
                {"version": 2, "name": "agent_public_network"},
                {"version": 3, "name": "activity_audit"},
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
            "upgrade_latest": 3,
            "pending_upgrades": [
                {"version": 1, "name": "discord_integration"},
                {"version": 2, "name": "agent_public_network"},
                {"version": 3, "name": "activity_audit"},
            ],
            "upgrade_error": None,
            "valid": False,
        }
        result = self.guard_classifier(payload)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
