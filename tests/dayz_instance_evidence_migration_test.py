import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'database'))
from instance_evidence_migration import migrate_sqlite, VERSION, NAME, CHECKSUM


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, checksum TEXT)')
        self.db.execute("INSERT INTO schema_migrations VALUES (41,'consolidated_schema','original-checksum')")
        self.db.executescript("""CREATE TABLE agent_instance_commands (
            command_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('status','doctor','start','stop','restart','remove')),
            status TEXT NOT NULL DEFAULT 'queued', requested_by TEXT,
            result_json TEXT, last_error TEXT, created_at TEXT,
            delivered_at TEXT, completed_at TEXT, updated_at TEXT
        );""")
        self.db.execute("INSERT INTO agent_instance_commands (command_id,agent_id,instance_id,action) VALUES ('old','agent','instance','status')")
        self.db.commit()

    def test_tracks_version_without_rewriting_baseline(self):
        self.assertTrue(migrate_sqlite(self.db))
        self.assertEqual(self.db.execute('SELECT checksum FROM schema_migrations WHERE version=41').fetchone()[0],'original-checksum')
        self.assertEqual(tuple(self.db.execute('SELECT name,checksum FROM schema_migrations WHERE version=43').fetchone()),(NAME,CHECKSUM))
        self.assertEqual(self.db.execute("SELECT action,parameters_json FROM agent_instance_commands WHERE command_id='old'").fetchone(),('status',None))

    def test_idempotent(self):
        migrate_sqlite(self.db)
        self.assertFalse(migrate_sqlite(self.db))

    def test_tampered_checksum_fails_closed(self):
        migrate_sqlite(self.db)
        self.db.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=43")
        self.db.commit()
        with self.assertRaises(RuntimeError):migrate_sqlite(self.db)

    def test_record_without_column_fails_closed(self):
        self.db.execute('INSERT INTO schema_migrations VALUES (?,?,?)',(VERSION,NAME,CHECKSUM))
        with self.assertRaises(RuntimeError):migrate_sqlite(self.db)


if __name__=='__main__':unittest.main()
