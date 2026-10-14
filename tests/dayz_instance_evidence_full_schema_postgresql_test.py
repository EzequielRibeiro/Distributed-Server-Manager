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
            db.execute('DROP SCHEMA IF EXISTS dayz_evidence_test CASCADE')
            db.execute('CREATE SCHEMA dayz_evidence_test')
            db.execute('SET search_path TO dayz_evidence_test')
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

    def test_migration_rolls_back_on_version_conflict(self):
        import psycopg
        with psycopg.connect('') as db:
            db.execute('DROP SCHEMA IF EXISTS dayz_evidence_test CASCADE')
            db.execute('CREATE SCHEMA dayz_evidence_test')
            db.execute('SET search_path TO dayz_evidence_test')
            db.execute((ROOT/'database/schemas/postgresql.sql').read_text())
            db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT)')
            db.execute("INSERT INTO schema_migrations VALUES(43,'unexpected_migration','bad-checksum')")
            db.commit()
            with self.assertRaises(RuntimeError):
                apply_evidence_migration(db,'postgresql')
            db.rollback()
            column=db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='agent_instance_commands' AND column_name='parameters_json'").fetchone()
            self.assertIsNone(column)
            action_type=db.execute("SELECT data_type,character_maximum_length FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='agent_instance_commands' AND column_name='action'").fetchone()
            self.assertEqual(action_type[0],'character varying')
            self.assertEqual(action_type[1],16)

    def test_repository_queue_roundtrip_on_migrated_postgresql(self):
        import psycopg
        from psycopg.rows import dict_row
        from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
        from contextlib import contextmanager

        with psycopg.connect('') as db:
            db.execute('DROP SCHEMA IF EXISTS dayz_evidence_test CASCADE')
            db.execute('CREATE SCHEMA dayz_evidence_test')
            db.execute('SET search_path TO dayz_evidence_test')
            db.execute((ROOT/'database/schemas/postgresql.sql').read_text())
            db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT)')
            db.execute("INSERT INTO schema_migrations VALUES(41,'consolidated_schema','baseline')")
            db.execute("INSERT INTO nodes(id,name,role) VALUES('controller-node','Controller','controller'),('agent-node','Agent','agent')")
            db.execute("INSERT INTO controllers(id,node_id,name) VALUES('controller-test','controller-node','Controller')")
            db.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES('agent-test','controller-test','agent-node','Agent','active')")
            db.execute("INSERT INTO customers(id,controller_id,name) VALUES('customer-test','controller-test','Customer')")
            db.execute("INSERT INTO instances(id,node_id,controller_id,agent_id,customer_id,game_id,name) VALUES('instance-test','agent-node','controller-test','agent-test','customer-test','dayz','DayZ')")
            db.commit()
            self.assertTrue(apply_evidence_migration(db,'postgresql'))
            db.commit()

        class IsolatedBackend:
            name='postgresql'
            def initialize(self): pass
            @contextmanager
            def connect(self):
                with psycopg.connect('',row_factory=dict_row,options='-c search_path=dayz_evidence_test') as connection:
                    yield connection
            transaction=connect

        repo=AgentInstanceRuntimeRepository(IsolatedBackend())
        params={'since':'2026-10-14T09:30:00Z','until':'2026-10-14T09:40:00Z'}
        queued=repo.enqueue(agent_id='agent-test',instance_id='instance-test',action='systemd_lifecycle_evidence',requested_by='maintenance-worker',parameters=params)
        command=repo.command_for_agent('agent-test')
        self.assertEqual(command['command_id'],queued['command_id'])
        self.assertEqual(command['since'],params['since'])
        self.assertEqual(command['until'],params['until'])
        repo.mark_delivered(command['command_id'])
        with self.assertRaises(PermissionError):
            repo.apply_result('wrong-agent',{'command_id':command['command_id'],'instance_id':'instance-test','action':'systemd_lifecycle_evidence','status':'completed'})
        with self.assertRaises(ValueError):
            repo.apply_result('agent-test',{'command_id':command['command_id'],'instance_id':'wrong-instance','action':'systemd_lifecycle_evidence','status':'completed'})
        with self.assertRaises(ValueError):
            repo.apply_result('agent-test',{'command_id':command['command_id'],'instance_id':'instance-test','action':'start','status':'completed'})
        self.assertEqual(repo.snapshot(command['command_id'])['status'],'delivered')
        completed=repo.apply_result('agent-test',{'command_id':command['command_id'],'instance_id':'instance-test','action':'systemd_lifecycle_evidence','status':'completed','result':{'verified_native_shutdown':False}})
        self.assertEqual(completed['status'],'completed')
        self.assertIsNone(repo.command_for_agent('agent-test'))

if __name__=='__main__':unittest.main()
