#!/usr/bin/env python3
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "database" / "manager.py"
SPEC = importlib.util.spec_from_file_location("database_manager", MANAGER_PATH)
DB = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DB
SPEC.loader.exec_module(DB)


class DatabaseManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "capivara.db"

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_database_status_does_not_create_file(self):
        result = DB.database_status(self.database)
        self.assertFalse(result["initialized"])
        self.assertEqual(result["health"], "missing")
        self.assertFalse(self.database.exists())

    def test_initialization_is_idempotent(self):
        first = DB.initialize(self.database)
        second = DB.initialize(self.database)

        self.assertTrue(first["initialized"])
        self.assertEqual(first["current_migration"], 5)
        self.assertEqual(first["applied_now"], [1, 3, 4, 5])
        self.assertEqual(second["applied_now"], [])
        self.assertTrue(
            {
                "schema_migrations",
                "nodes",
                "controllers",
                "agents",
                "customers",
                "instances",
                "operations",
                "events",
                "content_installations",
                "service_contracts",
                "instance_contracts",
                "dashboard_users",
                "instance_access",
                "audit_log",
            }.issubset(second["tables"])
        )

    def test_foreign_keys_and_content_cascade(self):
        DB.initialize(self.database)
        with closing(DB.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO nodes(id, name, role) VALUES (?, ?, ?)",
                ("controller1", "Controller 1", "controller"),
            )
            connection.execute(
                "INSERT INTO nodes(id, name, role) VALUES (?, ?, ?)",
                ("node1", "Node 1", "agent"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                ("controller1", "controller1", "Controller 1"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name) VALUES (?,?,?,?)",
                ("agent1", "controller1", "node1", "Agent 1"),
            )
            connection.execute(
                "INSERT INTO customers(id,controller_id,name) VALUES (?,?,?)",
                ("customer1", "controller1", "Cliente 1"),
            )
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?)",
                ("instance1", "node1", "minecraft", "Minecraft", "controller1", "agent1", "customer1"),
            )
            connection.execute(
                "INSERT INTO content_installations"
                "(instance_id, content_id, content_type, version) VALUES (?, ?, ?, ?)",
                ("instance1", "plugin1", "plugin", "1.0.0"),
            )
            connection.execute("DELETE FROM instances WHERE id = ?", ("instance1",))
            count = connection.execute(
                "SELECT COUNT(*) FROM content_installations"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_controller_agent_customer_instance_hierarchy_is_required(self):
        DB.initialize(self.database)
        with closing(DB.connect(self.database)) as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES ('controller1','Controller','controller')")
            connection.execute("INSERT INTO nodes(id,name,role) VALUES ('agent1','Agent','agent')")
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES ('controller1','controller1','Controller')")
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name) VALUES ('agent1','controller1','agent1','Agent')")
            connection.execute("INSERT INTO customers(id,controller_id,name) VALUES ('customer1','controller1','Cliente')")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "instance_requires_controller_agent_customer"):
                connection.execute("INSERT INTO instances(id,node_id,game_id,name) VALUES ('orphan','agent1','dayz','Órfã')")
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,controller_id,agent_id,customer_id) "
                "VALUES ('instance1','agent1','dayz','DayZ','controller1','agent1','customer1')"
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "agent_has_instances"):
                connection.execute("DELETE FROM agents WHERE id='agent1'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "customer_has_instances"):
                connection.execute("DELETE FROM customers WHERE id='customer1'")

    def test_backup_is_consistent_and_non_destructive(self):
        DB.initialize(self.database)
        backup = self.root / "backups" / "capivara.db"
        result = DB.backup_database(self.database, backup)

        self.assertGreater(result["size"], 0)
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        with self.assertRaisesRegex(DB.DatabaseError, "already exists"):
            DB.backup_database(self.database, backup)

    def test_changed_applied_migration_is_rejected(self):
        DB.initialize(self.database)
        migration = DB.load_migrations()[0]
        changed = replace(migration, checksum="0" * 64)
        with closing(DB.connect(self.database)) as connection:
            with self.assertRaisesRegex(DB.DatabaseError, "checksum does not match"):
                DB.apply_migrations(connection, [changed])

    def test_cli_status_returns_json(self):
        DB.initialize(self.database)
        completed = subprocess.run(
            [
                sys.executable,
                str(MANAGER_PATH),
                "--root",
                str(self.root),
                "--database",
                str(self.database),
                "status",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["kind"], "DatabaseStatus")
        self.assertEqual(result["current_migration"], 5)


if __name__ == "__main__":
    unittest.main()
