"""Regression test using the actual consolidated SQLite schema, not a toy table."""
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'database'))
from instance_evidence_migration import migrate_sqlite


class FullSchemaMigrationTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript((ROOT/'database/schemas/sqlite.sql').read_text())
        self.db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT)')
        self.db.execute("INSERT INTO schema_migrations VALUES (41,'consolidated_schema','baseline')")
        self.db.execute("INSERT INTO nodes(id,name,role) VALUES('node-test','Test','controller')")
        self.db.execute("INSERT INTO controllers(id,node_id,name) VALUES('controller-test','node-test','Test')")
        self.db.execute("INSERT INTO agents(id,controller_id,node_id,name) VALUES('agent-test','controller-test','node-test','Test')")
        self.db.execute("INSERT INTO instances(id,game_id,name) VALUES('instance-test','dayz','Test')")
        self.db.execute("INSERT INTO agent_instance_commands(command_id,agent_id,instance_id,action,status,requested_by,result_json,last_error) VALUES('sample','agent-test','instance-test','status','completed','tester','{}',NULL)")
        self.db.commit()

    def test_preserves_existing_command_and_integrity(self):
        before=dict(self.db.execute("SELECT * FROM agent_instance_commands WHERE command_id='sample'").fetchone())
        self.assertEqual(list(self.db.execute('PRAGMA foreign_key_check')),[])
        self.assertTrue(migrate_sqlite(self.db))
        after=dict(self.db.execute("SELECT * FROM agent_instance_commands WHERE command_id='sample'").fetchone())
        self.assertTrue(all(after[k]==v for k,v in before.items()))
        self.assertIsNone(after['parameters_json'])
        self.assertEqual(list(self.db.execute('PRAGMA foreign_key_check')),[])
        self.assertFalse(migrate_sqlite(self.db))

    def test_accepts_new_evidence_action_after_migration(self):
        migrate_sqlite(self.db)
        self.db.execute("INSERT INTO agent_instance_commands(command_id,agent_id,instance_id,action) VALUES('evidence','agent-test','instance-test','systemd_lifecycle_evidence')")
        self.assertEqual(self.db.execute("SELECT action FROM agent_instance_commands WHERE command_id='evidence'").fetchone()[0],'systemd_lifecycle_evidence')

if __name__=='__main__':unittest.main()
