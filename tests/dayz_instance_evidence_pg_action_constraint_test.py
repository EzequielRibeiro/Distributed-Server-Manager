import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'database'))
from instance_evidence_migration import migrate_postgresql

class PostgreSQLActionConstraintTest(unittest.TestCase):
    def test_widens_action_and_replaces_check(self):
        db=MagicMock()
        def execute(sql,*args):
            response=MagicMock()
            if 'FROM schema_migrations' in sql:response.fetchone.return_value=None
            if 'FROM pg_constraint' in sql:response.fetchall.return_value=[{'conname':'agent_instance_commands_action_check','definition':'CHECK (action = ANY (...))'}]
            return response
        db.execute.side_effect=execute
        self.assertTrue(migrate_postgresql(db))
        statements=[call.args[0] for call in db.execute.call_args_list]
        self.assertTrue(any('ALTER COLUMN action TYPE TEXT' in s for s in statements))
        self.assertTrue(any('DROP CONSTRAINT "agent_instance_commands_action_check"' in s for s in statements))
        self.assertTrue(any('systemd_lifecycle_evidence' in s and 'ADD CONSTRAINT' in s for s in statements))

if __name__=='__main__':unittest.main()
