import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'database'))
from instance_evidence_schema_upgrade import upgrade_evidence_parameters


class PostgreSQLUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.connection=MagicMock()
        self.cursor=self.connection.cursor.return_value

    def test_adds_column_if_missing(self):
        self.cursor.fetchone.return_value=None
        self.assertTrue(upgrade_evidence_parameters(self.connection,'postgresql'))
        sql=[call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertTrue(any('ADD COLUMN IF NOT EXISTS parameters_json' in value for value in sql))
        self.cursor.close.assert_called_once()

    def test_skips_column_if_present(self):
        self.cursor.fetchone.return_value=(1,)
        self.assertFalse(upgrade_evidence_parameters(self.connection,'postgresql'))
        sql=[call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertFalse(any('ALTER TABLE' in value for value in sql))

    def test_closes_cursor_on_error(self):
        self.cursor.execute.side_effect=RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):upgrade_evidence_parameters(self.connection,'postgresql')
        self.cursor.close.assert_called_once()


if __name__=='__main__':unittest.main()
