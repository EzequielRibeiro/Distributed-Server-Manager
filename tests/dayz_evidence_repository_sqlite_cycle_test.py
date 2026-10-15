"""Exercise command transport through the real repository with an isolated database."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'database'),str(ROOT)]
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from instance_evidence_migration import migrate_sqlite

class _Dialect:
    placeholder='?'
    def parameters(self,n):return ','.join('?' for _ in range(n))

class _Session:
    def __init__(self,connection):self.connection=connection
    def execute(self,sql,parameters=()):return self.connection.execute(sql,parameters)
    def close(self):pass

class _Context:
    def __init__(self,backend,transaction):self.backend=backend;self.transaction=transaction
    def __enter__(self):
        self.db=sqlite3.connect(self.backend.path)
        self.db.row_factory=sqlite3.Row
        return self.db
    def __exit__(self,exc_type,exc,tb):
        if exc_type:self.db.rollback()
        elif self.transaction:self.db.commit()
        self.db.close()

class _Backend:
    name='sqlite'
    def __init__(self,path):self.path=path
    def initialize(self):pass
    def connect(self):return _Context(self,False)
    def transaction(self):return _Context(self,True)

class EvidenceQueueTest(unittest.TestCase):
    def test_enqueue_deliver_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'isolated.sqlite')
            db=sqlite3.connect(path)
            db.executescript((ROOT/'database/schemas/sqlite.sql').read_text())
            db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT)')
            db.execute("INSERT INTO schema_migrations VALUES(41,'consolidated_schema','baseline')")
            db.execute("INSERT INTO nodes(id,name,role) VALUES('controller-node','Controller','controller'),('agent-node','Agent','agent')")
            db.execute("INSERT INTO controllers(id,node_id,name) VALUES('controller-test','controller-node','Controller')")
            db.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES('agent-test','controller-test','agent-node','Agent','active')")
            db.execute("INSERT INTO customers(id,controller_id,name) VALUES('customer-test','controller-test','Customer')")
            db.execute("INSERT INTO instances(id,node_id,controller_id,agent_id,customer_id,game_id,name) VALUES('instance-test','agent-node','controller-test','agent-test','customer-test','dayz','DayZ')")
            db.commit();migrate_sqlite(db);db.close()
            repo=AgentInstanceRuntimeRepository(_Backend(path))
            params={'since':'2026-10-14T09:30:00Z','until':'2026-10-14T09:40:00Z'}
            queued=repo.enqueue(agent_id='agent-test',instance_id='instance-test',action='systemd_lifecycle_evidence',requested_by='internal-test',parameters=params)
            command=repo.command_for_agent('agent-test')
            self.assertEqual(command['agent_id'],'agent-test')
            self.assertEqual(command['since'],params['since'])
            self.assertEqual(command['until'],params['until'])
            # Agent executes the exact queued Controller command against a
            # mocked journal; no systemd unit or production files are touched.
            from unittest.mock import patch
            sys.path.insert(0,str(ROOT/'agents/linux/runtime'))
            sys.path.insert(0,str(ROOT/'dashboard/workers'))
            import instance_runtime as agent_runtime
            from dayz_evidence_result import authenticated_restart_observation
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as agent_folder:
                with patch.object(agent_runtime,'HISTORY_DIR',Path(agent_folder)/'history'), patch.object(agent_runtime,'RESULT_DIR',Path(agent_folder)/'results'):
                    record={'instance_id':'instance-test','agent_id':'agent-test','adapter':'systemd'}
                    unit='capivara-instance-instance-test.service'
                    events=[{'unit':unit,'event':'stopped','at':'2026-10-14T09:35:00Z'},
                            {'unit':unit,'event':'started','at':'2026-10-14T09:36:00Z'}]
                    with patch.object(agent_runtime,'get_instance',return_value=record), patch('systemd_journal_reader.read_systemd_transitions',return_value=events) as reader:
                        agent_result=agent_runtime.handle_command({'agent_id':'agent-test'},command)
                    self.assertEqual(agent_result['status'],'completed')
                    reader.assert_called_once()
            repo.mark_delivered(command['command_id'])
            completed=repo.apply_result('agent-test',agent_result)
            self.assertEqual(completed['status'],'completed')
            self.assertTrue(authenticated_restart_observation(
                command=repo.snapshot(command['command_id']),
                agent_id='agent-test',instance_id='instance-test',
                since=params['since'],until=params['until']))
            self.assertIsNone(repo.command_for_agent('agent-test'))

if __name__=='__main__':unittest.main()
