"""Integration tests for a disposable real PostgreSQL database (PG* environment)."""
import os
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'database'))
from instance_evidence_migration import apply_evidence_migration


@unittest.skipUnless(os.environ.get('PGHOST') and os.environ.get('CAPIVARA_TEST_DISPOSABLE_PG')=='1', 'requires disposable PostgreSQL')
class PostgreSQLFullSchemaTest(unittest.TestCase):
    def test_preserve_existing_command(self):
        import psycopg
        with psycopg.connect('') as db:
            db.execute((ROOT/'database/schemas/postgresql.sql').read_text())
            db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT)')
            db.execute("INSERT INTO schema_migrations VALUES(41,'consolidated_schema','baseline')")
            db.execute("INSERT INTO nodes(id,name,role) VALUES('controller-node','Controller','controller'),('agent-node','Agent','agent')")
            db.execute("INSERT INTO controllers(id,node_id,name) VALUES('controller-test','controller-node','Controller')")
            db.execute("INSERT INTO agents(id,controller_id,node_id,name) VALUES('agent-test','controller-test','agent-node','Agent')")
            db.execute("INSERT INTO customers(id,controller_id,name) VALUES('customer-test','controller-test','Customer')")
            db.execute("INSERT INTO instances(id,node_id,controller_id,agent_id,customer_id,game_id,name) VALUES('instance-test','agent-node','controller-test','agent-test','customer-test','dayz','DayZ')")
            db.execute("INSERT INTO agent_instance_commands(command_id,agent_id,instance_id,action,status,requested_by,result_json) VALUES('command-old','agent-test','instance-test','status','completed','tester','{}')")
            db.commit()
            before=db.execute("SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,created_at FROM agent_instance_commands WHERE command_id='command-old'").fetchone()
            self.assertTrue(apply_evidence_migration(db,'postgresql'))
            db.commit()
            after=db.execute("SELECT command_id,agent_id,instance_id,action,status,requested_by,result_json,created_at FROM agent_instance_commands WHERE command_id='command-old'").fetchone()
            self.assertEqual(before,after)
            self.assertFalse(apply_evidence_migration(db,'postgresql'))
            db.commit()
            db.execute("INSERT INTO agent_instance_commands(command_id,agent_id,instance_id,action,parameters_json) VALUES('command-new','agent-test','instance-test','systemd_lifecycle_evidence','{}')")
            self.assertEqual(db.execute("SELECT parameters_json FROM agent_instance_commands WHERE command_id='command-new'").fetchone()[0],'{}')

if __name__=='__main__':unittest.main()
