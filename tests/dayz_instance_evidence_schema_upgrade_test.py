import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'database'))
from instance_evidence_schema_upgrade import upgrade_evidence_parameters


class EvidenceSchemaUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE agent_instance_commands (command_id TEXT PRIMARY KEY, action TEXT NOT NULL)')
        self.db.execute("INSERT INTO agent_instance_commands VALUES ('cmd-1','status')")

    def test_add_column_and_preserve_existing_rows(self):
        self.assertTrue(upgrade_evidence_parameters(self.db, 'sqlite'))
        self.assertEqual(self.db.execute("SELECT action, parameters_json FROM agent_instance_commands WHERE command_id='cmd-1'").fetchone(), ('status',None))

    def test_repeated_upgrade_noop(self):
        self.assertTrue(upgrade_evidence_parameters(self.db,'sqlite'))
        self.assertFalse(upgrade_evidence_parameters(self.db,'sqlite'))

    def test_missing_table_fails_closed(self):
        self.db.execute('DROP TABLE agent_instance_commands')
        with self.assertRaises(RuntimeError): upgrade_evidence_parameters(self.db,'sqlite')

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError): upgrade_evidence_parameters(self.db,'mysql')


if __name__=='__main__': unittest.main()
