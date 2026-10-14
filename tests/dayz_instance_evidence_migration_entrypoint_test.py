import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'database'))
from instance_evidence_migration import apply_evidence_migration

class EntrypointTest(unittest.TestCase):
    def test_sqlite_upgrade(self):
        db=sqlite3.connect(':memory:')
        try:
            db.executescript('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT); CREATE TABLE agent_instance_commands(command_id TEXT PRIMARY KEY);')
            self.assertTrue(apply_evidence_migration(db,'sqlite'))
            self.assertFalse(apply_evidence_migration(db,'sqlite'))
        finally:db.close()

    def test_sqlite_rejects_existing_transaction(self):
        db=sqlite3.connect(':memory:')
        try:
            db.execute('BEGIN')
            with self.assertRaises(RuntimeError):apply_evidence_migration(db,'sqlite')
            db.rollback()
        finally:db.close()

    def test_postgres_transaction_context(self):
        db=MagicMock()
        db.execute.return_value.fetchone.return_value=None
        self.assertTrue(apply_evidence_migration(db,'postgresql'))
        db.transaction.assert_called_once_with()
        db.transaction.return_value.__enter__.assert_called_once()
        db.transaction.return_value.__exit__.assert_called_once()

    def test_postgres_failure_exits_context_with_exception(self):
        db=MagicMock()
        db.execute.side_effect=RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):apply_evidence_migration(db,'postgresql')
        args=db.transaction.return_value.__exit__.call_args.args
        self.assertIs(args[0],RuntimeError)

if __name__=='__main__':unittest.main()
