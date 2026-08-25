#!/usr/bin/env python3
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "database" / "manager.py"
SPEC = importlib.util.spec_from_file_location("database_manager", MANAGER_PATH)
DB = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DB
SPEC.loader.exec_module(DB)
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from runtime_backend import backend_from_environment


class DatabaseManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "capivara.db"

    def tearDown(self):
        self.temp.cleanup()

    def _baseline_backend(self):
        return backend_from_environment({
            "DSM_DATABASE_DRIVER": "sqlite",
            "DSM_DATABASE": str(self.database),
        })

    def test_missing_database_status_does_not_create_file(self):
        result = DB.database_status(self.database)
        self.assertFalse(result["initialized"])
        self.assertEqual(result["health"], "missing")
        self.assertFalse(self.database.exists())

    def test_baseline_initialization_is_idempotent(self):
        backend = self._baseline_backend()
        first = backend.initialize()
        second = backend.initialize()
        self.assertTrue(first["initialized"])
        self.assertEqual(first["baseline"], "capivara-baseline-v2")
        self.assertTrue(first["installed_now"])
        self.assertFalse(second["installed_now"])
        self.assertEqual(second["baseline_checksum"], first["baseline_checksum"])
        self.assertIn("schema_baseline", second["tables"])
        self.assertNotIn("schema_migrations", second["tables"])

    def test_foreign_keys_and_content_cascade(self):
        backend = self._baseline_backend(); backend.initialize()
        with closing(DB.connect(self.database)) as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("controller1","Controller 1","controller"))
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node1","Node 1","agent"))
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller1","controller1","Controller 1"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name) VALUES (?,?,?,?)",("agent1","controller1","node1","Agent 1"))
            cursor=connection.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller1","Cliente 1")); customer_id=cursor.lastrowid
            connection.execute("INSERT INTO instances(id,node_id,game_id,name,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?)",("instance1","node1","minecraft","Minecraft","controller1","agent1",customer_id))
            connection.execute("INSERT INTO content_installations(instance_id,content_id,content_type,version) VALUES (?,?,?,?)",("instance1","plugin1","plugin","1.0.0"))
            connection.execute("DELETE FROM instances WHERE id=?",("instance1",))
            count=connection.execute("SELECT COUNT(*) FROM content_installations").fetchone()[0]
        self.assertEqual(count,0)

    def test_controller_agent_customer_instance_hierarchy_is_required(self):
        backend = self._baseline_backend(); backend.initialize()
        with closing(DB.connect(self.database)) as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES ('controller1','Controller','controller')")
            connection.execute("INSERT INTO nodes(id,name,role) VALUES ('agent1','Agent','agent')")
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES ('controller1','controller1','Controller')")
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name) VALUES ('agent1','controller1','agent1','Agent')")
            customer_id=connection.execute("INSERT INTO customers(controller_id,name) VALUES ('controller1','Cliente')").lastrowid
            with self.assertRaisesRegex(sqlite3.IntegrityError,"instance_requires_controller_agent_customer"):
                connection.execute("INSERT INTO instances(id,node_id,game_id,name) VALUES ('orphan','agent1','dayz','Órfã')")
            connection.execute("INSERT INTO instances(id,node_id,game_id,name,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?)",("instance1","agent1","dayz","DayZ","controller1","agent1",customer_id))
            with self.assertRaisesRegex(sqlite3.IntegrityError,"agent_has_instances"):
                connection.execute("DELETE FROM agents WHERE id='agent1'")
            with self.assertRaisesRegex(sqlite3.IntegrityError,"customer_has_instances"):
                connection.execute("DELETE FROM customers WHERE id=?",(customer_id,))

    def test_backup_is_consistent_and_non_destructive(self):
        self._baseline_backend().initialize()
        backup=self.root/"backups"/"capivara.db"
        result=DB.backup_database(self.database,backup)
        self.assertGreater(result["size"],0)
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0],"ok")
        with self.assertRaisesRegex(DB.DatabaseError,"already exists"):
            DB.backup_database(self.database,backup)

    def test_new_install_uses_one_baseline_marker_not_migration_ledger(self):
        backend=self._baseline_backend(); result=backend.initialize()
        self.assertEqual(result["baseline"],"capivara-baseline-v2")
        with closing(DB.connect(self.database)) as connection:
            marker=connection.execute("SELECT name,checksum FROM schema_baseline").fetchone()
            old=connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
        self.assertEqual(marker[0],"capivara-baseline-v2")
        self.assertEqual(len(marker[1]),64)
        self.assertIsNone(old)

    def test_cli_status_returns_baseline_json(self):
        self._baseline_backend().initialize()
        completed=subprocess.run([sys.executable,str(MANAGER_PATH),"--root",str(self.root),"--database",str(self.database),"status"],check=True,capture_output=True,text=True)
        result=json.loads(completed.stdout)
        self.assertEqual(result["kind"],"DatabaseStatus")
        self.assertEqual(result["baseline"],"capivara-baseline-v2")
        self.assertTrue(result["checksum_matches"])
        self.assertNotIn("current_migration",result)


if __name__=="__main__":
    unittest.main()
