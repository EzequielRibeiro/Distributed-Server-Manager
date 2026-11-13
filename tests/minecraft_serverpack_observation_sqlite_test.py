"""Real isolated SQLite event persistence, ownership and idempotence."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
for folder in ('dashboard','database'):
    sys.path.insert(0,str(ROOT/folder))
from backend import DatabaseConfig
from backends.sqlite_backend import SQLiteBackend
from minecraft_serverpack_observation_events import persist_serverpack_runtime_observations
from universal_event_repository import UniversalEventRepository

class ServerPackObservationSQLiteTest(unittest.TestCase):
    def test_local_agent_observation_is_idempotent_and_never_a_runtime_health_claim(self):
        with tempfile.TemporaryDirectory(prefix='dsm-observation-sqlite-') as name:
            backend=SQLiteBackend(DatabaseConfig(driver='sqlite',database=str(Path(name)/'db.sqlite')))
            try:
                backend.initialize()
                with backend.transaction() as c:
                    c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('ctrl-node','Controller','controller'))
                    c.execute('INSERT INTO nodes(id,name,role) VALUES (?,?,?)',('agent-node','Agent','agent'))
                    c.execute('INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)',('ctrl','ctrl-node','Controller'))
                    c.execute('INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)',
                              ('agent','ctrl','agent-node','Agent','active'))
                    c.execute('INSERT INTO customers(id,controller_id,name) VALUES (?,?,?)',('customer','ctrl','Customer'))
                    c.execute('INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id,game_version,build_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                              ('inst','agent-node','minecraft','minecraft.java.neoforge','Lab','stopped','ctrl','agent','customer','26.1.2','26.1.2.109'))
                observation={'instance_id':'inst','content_id':'pack','bundle_revision':2,
                             'status':'physical_runtime_verified','reason':'boot_not_observed',
                             'boot_verified':False,'ready_for_release':False}
                timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
                first=persist_serverpack_runtime_observations(backend,agent_id='agent',
                            observations=[observation],observed_at=timestamp)
                second=persist_serverpack_runtime_observations(backend,agent_id='agent',
                            observations=[observation],observed_at=timestamp)
                foreign=persist_serverpack_runtime_observations(backend,agent_id='foreign',
                            observations=[observation],observed_at=timestamp)
                self.assertEqual(first,{'accepted':1,'created':1})
                self.assertEqual(second,{'accepted':1,'created':0})
                self.assertEqual(foreign,{'accepted':0,'created':0})
                events=UniversalEventRepository(backend).list_events(
                    limit=10,event_type='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',instance_id='inst')
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]['data']['proof_scope'],'current_filesystem_only')
                self.assertIs(events[0]['data']['boot_verified'],False)
                self.assertIs(events[0]['data']['release_authorized'],False)
            finally:
                backend.close()

if __name__=='__main__':unittest.main()