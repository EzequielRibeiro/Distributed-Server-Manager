#!/usr/bin/env python3
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATABASE=ROOT/"database"
if str(DATABASE) not in sys.path:sys.path.insert(0,str(DATABASE))
from backend import DatabaseMigrationError
from baseline_upgrade_engine import UPGRADES,apply_pending_upgrades,latest_upgrade_version,upgrade_status

class SQLiteBackend:
    name="sqlite"

class ContentContractV2BaselineUpgradeTest(unittest.TestCase):
    def old_connection(self):
        connection=sqlite3.connect(":memory:")
        connection.row_factory=sqlite3.Row
        connection.executescript("""
CREATE TABLE content_assignments(id TEXT PRIMARY KEY);
CREATE TABLE content_assignment_revisions(id TEXT PRIMARY KEY);
CREATE TABLE agent_content_state(id TEXT PRIMARY KEY);
CREATE TABLE backup_jobs(command_id TEXT PRIMARY KEY,backup_id TEXT,action TEXT,status TEXT);
CREATE TABLE datacenters(id TEXT PRIMARY KEY,region_id TEXT,name TEXT,provider TEXT,city TEXT,country_code TEXT,latitude REAL,longitude REAL,status TEXT);
CREATE UNIQUE INDEX idx_backup_jobs_backup_id ON backup_jobs(backup_id) WHERE backup_id IS NOT NULL;
CREATE TABLE baseline_upgrades(version INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT INTO content_assignments(id) VALUES ('assignment-1');
INSERT INTO content_assignment_revisions(id) VALUES ('revision-1');
INSERT INTO agent_content_state(id) VALUES ('state-1');
""")
        for upgrade in UPGRADES[:7]:
            connection.execute("INSERT INTO baseline_upgrades(version,name) VALUES (?,?)",(upgrade.version,upgrade.name))
        connection.commit()
        return connection

    def test_ledger_v7_materializes_content_contract_v2_and_retry_repair(self):
        connection=self.old_connection()
        try:
            completed=apply_pending_upgrades(SQLiteBackend(),connection,installed_checksum="historical-v7-checksum")
            self.assertEqual(completed,[upgrade.version for upgrade in UPGRADES if upgrade.version >= 8])
            self.assertEqual(upgrade_status(SQLiteBackend(),connection)["current_version"],latest_upgrade_version())
            row=connection.execute("SELECT activation_state,activation_order,provenance_json,metadata_json,security_state FROM content_assignments").fetchone()
            self.assertEqual(tuple(row),("enabled",0,"{}","{}","unscanned"))
            revision=connection.execute("SELECT activation_state,activation_order,provenance_json,metadata_json,security_state FROM content_assignment_revisions").fetchone()
            self.assertEqual(tuple(revision),("enabled",0,"{}","{}","unscanned"))
            self.assertEqual(connection.execute("SELECT security_state FROM agent_content_state").fetchone()[0],"unscanned")
        finally:
            connection.close()

    def test_partial_content_contract_v2_is_rejected(self):
        connection=self.old_connection()
        try:
            connection.execute("ALTER TABLE content_assignments ADD COLUMN activation_state TEXT NOT NULL DEFAULT 'enabled'")
            with self.assertRaisesRegex(DatabaseMigrationError,"partial Universal Content Contract v2"):
                apply_pending_upgrades(SQLiteBackend(),connection,installed_checksum="historical-v7-checksum")
        finally:
            connection.close()

    def test_checksum_mismatch_with_v7_ledger_reconciles_through_latest(self):
        manager=ROOT/"database"/"manager.py"
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"dsm"
            database=root/"data"/"capivara.db"
            database.parent.mkdir(parents=True)
            def run(command):
                return subprocess.run(["python3",str(manager),"--root",str(root),"--driver","sqlite","--database",str(database),command],cwd=ROOT,text=True,capture_output=True,check=False)
            initialized=run("init")
            self.assertEqual(initialized.returncode,0,initialized.stderr)
            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM baseline_upgrades WHERE version>=8")
                connection.execute("DROP INDEX IF EXISTS idx_backup_jobs_backup_id")
                connection.execute("CREATE UNIQUE INDEX idx_backup_jobs_backup_id ON backup_jobs(backup_id) WHERE backup_id IS NOT NULL")
                connection.execute("UPDATE schema_baseline SET checksum=?",("historical-v7-baseline-checksum",))
                connection.commit()
            before=run("check")
            self.assertEqual(before.returncode,1,before.stderr)
            payload=json.loads(before.stdout)
            self.assertEqual(payload["upgrade_version"],7)
            self.assertEqual(payload["upgrade_latest"],latest_upgrade_version())
            self.assertEqual(payload["pending_upgrades"],[{"version":upgrade.version,"name":upgrade.name} for upgrade in UPGRADES if upgrade.version >= 8])
            migrated=run("migrate")
            self.assertEqual(migrated.returncode,0,migrated.stderr)
            payload=json.loads(migrated.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["upgrade_version"],latest_upgrade_version())
            self.assertTrue(payload["checksum_matches"])

if __name__=="__main__":
    unittest.main()
