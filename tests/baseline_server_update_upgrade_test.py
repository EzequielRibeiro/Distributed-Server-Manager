#!/usr/bin/env python3
"""Regression coverage for the Baseline v2 universal server-update upgrade."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "database" / "manager.py"
SERVER_UPDATE_TABLES = {
    "instance_update_policy",
    "instance_update_state",
    "instance_update_runs",
}


class BaselineServerUpdateUpgradeTest(unittest.TestCase):
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

    def test_upgrade_from_ledger_v5_materializes_server_update_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version=6")
                for table in SERVER_UPDATE_TABLES:
                    connection.execute(f"DROP TABLE {table}")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=?",
                    ("historical-v5-baseline-checksum",),
                )
                connection.commit()

            before = self.manager(root, database, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            before_payload = json.loads(before.stdout)
            self.assertEqual(before_payload["upgrade_version"], 5)
            self.assertEqual(before_payload["upgrade_latest"], 6)
            self.assertEqual(
                before_payload["pending_upgrades"],
                [{"version": 6, "name": "universal_server_update"}],
            )

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertTrue(migrated_payload["valid"])
            self.assertEqual(migrated_payload["upgrade_version"], 6)
            self.assertEqual(migrated_payload["upgrade_latest"], 6)

            with sqlite3.connect(database) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version=6"
                ).fetchone()

            self.assertTrue(SERVER_UPDATE_TABLES <= tables)
            self.assertEqual(ledger, (6, "universal_server_update"))

    def test_partial_server_update_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version=6")
                connection.execute("DROP TABLE instance_update_state")
                connection.execute("DROP TABLE instance_update_runs")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=?",
                    ("historical-v5-baseline-checksum",),
                )
                connection.commit()

            migrated = self.manager(root, database, "migrate")
            self.assertNotEqual(migrated.returncode, 0)
            self.assertIn(
                "partial universal server update baseline upgrade",
                migrated.stdout + migrated.stderr,
            )


if __name__ == "__main__":
    unittest.main()
