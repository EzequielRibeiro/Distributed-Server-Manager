import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'database'))
from instance_evidence_migration import migrate_postgresql, NAME, CHECKSUM


class PostgreSQLMigrationTest(unittest.TestCase):
    def setUp(self):
        self.db=MagicMock()

    def test_new_migration(self):
        self.db.execute.return_value.fetchone.return_value=None
        self.assertTrue(migrate_postgresql(self.db))
        statements=[c.args[0] for c in self.db.execute.call_args_list]
        self.assertTrue(any('ADD COLUMN IF NOT EXISTS parameters_json' in x for x in statements))
        self.assertTrue(any('INSERT INTO schema_migrations' in x for x in statements))
        self.db.commit.assert_not_called()

    def test_existing_valid_migration(self):
        self.db.execute.return_value.fetchone.side_effect=[(NAME,CHECKSUM),(1,)]
        self.assertFalse(migrate_postgresql(self.db))
        self.assertFalse(any('ALTER TABLE' in c.args[0] for c in self.db.execute.call_args_list))

    def test_tampered_checksum_rejected(self):
        self.db.execute.return_value.fetchone.return_value=(NAME,'incorrect')
        with self.assertRaises(RuntimeError):migrate_postgresql(self.db)
        self.assertEqual(self.db.execute.call_count,1)

    def test_recorded_column_missing_rejected(self):
        self.db.execute.return_value.fetchone.side_effect=[(NAME,CHECKSUM),None]
        with self.assertRaises(RuntimeError):migrate_postgresql(self.db)


if __name__=='__main__':unittest.main()
