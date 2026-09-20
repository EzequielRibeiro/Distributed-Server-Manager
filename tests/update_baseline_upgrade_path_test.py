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

    def test_migrate_advances_v10_through_current_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version>=11")
                for table in (
                    "instance_maintenance_runs",
                    "instance_maintenance_state",
                    "instance_maintenance_policy",
                    "content_update_state",
                    "content_update_policy",
                ):
                    connection.execute(f"DROP TABLE {table}")
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
            self.assertEqual(payload["upgrade_version"], latest_upgrade_version())
            self.assertEqual(payload["upgrade_latest"], latest_upgrade_version())
            self.assertTrue(payload["valid"])

            with sqlite3.connect(database) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info('datacenters')")
                }
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version>=11 ORDER BY version"
                ).fetchall()

            self.assertTrue({"country_name", "state_code", "state_name"} <= columns)
            self.assertEqual(
                ledger,
                [
                    (11, "datacenter_geography_metadata"),
                    (12, "universal_content_update"),
                    (13, "maintenance_restart_framework"),
                    (14, "yarax_admin_operations"),
                    (15, "dayz_native_restart_commands"),
                    (16, "generic_native_restart_commands"),
                ],
            )

    def test_migrate_2062_v11_database_through_content_and_maintenance(self) -> None:
        old_2062_checksum = "b8d7de4a314faf5086bf02bcbc626dbbef94ba1a84eb2490f068cbb74c7634ce"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version>=12")
                for table in (
                    "instance_maintenance_runs",
                    "instance_maintenance_state",
                    "instance_maintenance_policy",
                    "content_update_state",
                    "content_update_policy",
                ):
                    connection.execute(f"DROP TABLE {table}")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",
                    (old_2062_checksum,),
                )
                connection.commit()

            before = self.manager(root, database, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            before_payload = json.loads(before.stdout)
            self.assertEqual(before_payload["upgrade_version"], 11)
            self.assertEqual(before_payload["upgrade_latest"], latest_upgrade_version())
            self.assertEqual(
                before_payload["pending_upgrades"],
                [
                    {"version": 12, "name": "universal_content_update"},
                    {"version": 13, "name": "maintenance_restart_framework"},
                    {"version": 14, "name": "yarax_admin_operations"},
                    {"version": 15, "name": "dayz_native_restart_commands"},
                    {"version": 16, "name": "generic_native_restart_commands"},
                ],
            )
            self.assertEqual(self.guard_classifier(before_payload).returncode, 0)

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertTrue(migrated_payload["valid"])
            self.assertEqual(migrated_payload["upgrade_version"], latest_upgrade_version())
            self.assertEqual(migrated_payload["upgrade_latest"], latest_upgrade_version())

            with sqlite3.connect(database) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                indexes = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    ).fetchall()
                }
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version>=12 ORDER BY version"
                ).fetchall()

            self.assertTrue(
                {
                    "content_update_policy",
                    "content_update_state",
                    "instance_maintenance_policy",
                    "instance_maintenance_state",
                    "instance_maintenance_runs",
                } <= tables
            )
            self.assertTrue(
                {
                    "idx_content_update_state_instance",
                    "idx_content_update_state_agent",
                    "idx_instance_maintenance_state_due",
                    "idx_instance_maintenance_runs_instance",
                } <= indexes
            )
            self.assertEqual(
                ledger,
                [
                    (12, "universal_content_update"),
                    (13, "maintenance_restart_framework"),
                    (14, "yarax_admin_operations"),
                    (15, "dayz_native_restart_commands"),
                    (16, "generic_native_restart_commands"),
                ],
            )

    def test_migrate_2063_v11_existing_content_schema_is_idempotent(self) -> None:
        old_2063_checksum = "c328a768093c98600742ccf73ef01832a99190e3eee0f28e707b0f59a8a63189"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version>=12")
                for table in (
                    "instance_maintenance_runs",
                    "instance_maintenance_state",
                    "instance_maintenance_policy",
                ):
                    connection.execute(f"DROP TABLE {table}")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",
                    (old_2063_checksum,),
                )
                connection.commit()

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            payload = json.loads(migrated.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["upgrade_version"], latest_upgrade_version())

            with sqlite3.connect(database) as connection:
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version>=12 ORDER BY version"
                ).fetchall()
            self.assertEqual(
                ledger,
                [
                    (12, "universal_content_update"),
                    (13, "maintenance_restart_framework"),
                    (14, "yarax_admin_operations"),
                    (15, "dayz_native_restart_commands"),
                    (16, "generic_native_restart_commands"),
                ],
            )

    def test_migrate_advances_v13_database_through_yarax_admin_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version>=14")
                connection.execute("DROP TABLE yarax_admin_operations")
                connection.execute("DROP TABLE dayz_native_restart_commands")
                connection.execute("DROP TABLE native_restart_commands")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",
                    ("v13-checksum-simulation",),
                )
                connection.commit()

            before = self.manager(root, database, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            before_payload = json.loads(before.stdout)
            self.assertEqual(before_payload["upgrade_version"], 13)
            self.assertEqual(before_payload["upgrade_latest"], 16)
            self.assertEqual(
                before_payload["pending_upgrades"],
                [
                    {"version": 14, "name": "yarax_admin_operations"},
                    {"version": 15, "name": "dayz_native_restart_commands"},
                    {"version": 16, "name": "generic_native_restart_commands"},
                ],
            )
            self.assertEqual(self.guard_classifier(before_payload).returncode, 0)

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertTrue(migrated_payload["valid"])
            self.assertEqual(migrated_payload["upgrade_version"], 16)
            self.assertEqual(migrated_payload["upgrade_latest"], 16)

            with sqlite3.connect(database) as connection:
                table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='yarax_admin_operations'"
                ).fetchone()
                dayz_table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='dayz_native_restart_commands'"
                ).fetchone()
                generic_table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='native_restart_commands'"
                ).fetchone()
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version>=14 ORDER BY version"
                ).fetchall()

            self.assertEqual(table, ("yarax_admin_operations",))
            self.assertIsNone(dayz_table)
            self.assertEqual(generic_table, ("native_restart_commands",))
            self.assertEqual(
                ledger,
                [
                    (14, "yarax_admin_operations"),
                    (15, "dayz_native_restart_commands"),
                    (16, "generic_native_restart_commands"),
                ],
            )

    def test_migrate_advances_v14_database_through_dayz_native_restart_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version>=15")
                connection.execute("DROP TABLE native_restart_commands")
                connection.execute(
                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",
                    ("v14-checksum-simulation",),
                )
                connection.commit()

            before = self.manager(root, database, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            before_payload = json.loads(before.stdout)
            self.assertEqual(before_payload["upgrade_version"], 14)
            self.assertEqual(before_payload["upgrade_latest"], 15)
            self.assertEqual(
                before_payload["pending_upgrades"],
                [
                    {"version": 15, "name": "dayz_native_restart_commands"},
                    {"version": 16, "name": "generic_native_restart_commands"},
                ],
            )
            self.assertEqual(self.guard_classifier(before_payload).returncode, 0)

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertTrue(migrated_payload["valid"])
            self.assertEqual(migrated_payload["upgrade_version"], 15)
            self.assertEqual(migrated_payload["upgrade_latest"], 15)

            with sqlite3.connect(database) as connection:
                legacy_table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='dayz_native_restart_commands'"
                ).fetchone()
                table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='native_restart_commands'"
                ).fetchone()
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version>=15 ORDER BY version"
                ).fetchall()

            self.assertIsNone(legacy_table)
            self.assertEqual(table, ("native_restart_commands",))
            self.assertEqual(
                ledger,
                [
                    (15, "dayz_native_restart_commands"),
                    (16, "generic_native_restart_commands"),
                ],
            )

    def test_migrate_v15_dayz_queue_into_generic_native_restart_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            database = root / "data" / "capivara.db"
            database.parent.mkdir(parents=True)

            initialized = self.manager(root, database, "init")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            with sqlite3.connect(database) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("DELETE FROM baseline_upgrades WHERE version=16")
                connection.execute("DROP TABLE native_restart_commands")
                connection.executescript(
                    """
                    CREATE TABLE dayz_native_restart_commands (
                     command_id TEXT PRIMARY KEY,
                     agent_id TEXT NOT NULL,
                     instance_id TEXT NOT NULL,
                     due_at TEXT NOT NULL,
                     status VARCHAR(32) NOT NULL,
                     requested_by TEXT,
                     result_json TEXT,
                     last_error TEXT,
                     created_at TEXT NOT NULL,
                     delivered_at TEXT,
                     completed_at TEXT,
                     updated_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_dayz_native_restart_agent_status
                      ON dayz_native_restart_commands(agent_id,status,created_at);
                    CREATE INDEX idx_dayz_native_restart_instance_status
                      ON dayz_native_restart_commands(instance_id,status,created_at);
                    """
                )
                agent_id = connection.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
                instance = connection.execute(
                    "SELECT id,game_id,runtime_id FROM instances WHERE agent_id=? LIMIT 1",
                    (agent_id,),
                ).fetchone()
                if instance is None:
                    node_id = connection.execute("SELECT id FROM nodes LIMIT 1").fetchone()[0]
                    connection.execute(
                        "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,agent_id,created_at,updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        ("dayz-v15-test", node_id, "dayz", "dayz.stable", "DayZ v15", "running", agent_id,
                         "2026-09-20T00:00:00Z", "2026-09-20T00:00:00Z"),
                    )
                    instance_id = "dayz-v15-test"
                else:
                    instance_id = instance[0]
                    connection.execute(
                        "UPDATE instances SET game_id='dayz',runtime_id='dayz.stable' WHERE id=?",
                        (instance_id,),
                    )
                connection.execute(
                    "INSERT INTO dayz_native_restart_commands("
                    "command_id,agent_id,instance_id,due_at,status,requested_by,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?)",
                    ("dayz-maint-v15", agent_id, instance_id, "2026-09-20T01:00:00Z", "queued",
                     "test", "2026-09-20T00:00:00Z", "2026-09-20T00:00:00Z"),
                )
                connection.commit()

            migrated = self.manager(root, database, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)

            with sqlite3.connect(database) as connection:
                legacy = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='dayz_native_restart_commands'"
                ).fetchone()
                row = connection.execute(
                    "SELECT command_id,game_id,runtime_id,strategy,status "
                    "FROM native_restart_commands WHERE command_id='dayz-maint-v15'"
                ).fetchone()
                ledger = connection.execute(
                    "SELECT version,name FROM baseline_upgrades WHERE version=16"
                ).fetchone()

            self.assertIsNone(legacy)
            self.assertEqual(
                row,
                ("dayz-maint-v15", "dayz", "dayz.stable", "dayz-shutdown-messages", "queued"),
            )
            self.assertEqual(ledger, (16, "generic_native_restart_commands"))

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

    def test_process_guard_rejects_checksum_mismatch_without_pending_upgrade(self) -> None:
        payload = {
            "schema_version": 2,
            "kind": "DatabaseCheck",
            "driver": "postgresql",
            "connected": True,
            "initialized": True,
            "health": "error",
            "baseline": "capivara-baseline-v2",
            "baseline_checksum": "historical",
            "expected_baseline": "capivara-baseline-v2",
            "expected_checksum": "current",
            "checksum_matches": False,
            "missing_tables": [],
            "upgrade_ledger": True,
            "upgrade_version": latest_upgrade_version(),
            "upgrade_latest": latest_upgrade_version(),
            "pending_upgrades": [],
            "upgrade_error": None,
            "valid": False,
        }
        result = self.guard_classifier(payload)
        self.assertNotEqual(result.returncode, 0)

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
