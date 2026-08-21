#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard",ROOT/"dashboard"/"workers"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from automation_repository import AutomationRepository
from automation_worker import AutomationWorker,cron_matches
from backend import DatabaseConfig
from backend_factory import create_backend
from universal_event_repository import UniversalEventRepository
class AutomationWorkerTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.temp.name)/"worker.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("controller-node","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-w","controller-node","W"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-w","controller-w","agent-node","Agent","active"));c.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",("customer-w","controller-w","Customer","active"));c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-w","agent-node","game.generic","Generic","offline","controller-w","agent-w","customer-w"))
  self.repo=AutomationRepository(self.backend);self.repo.initialize();self.worker=AutomationWorker(self.backend)
 def tearDown(self):self.backend.close();self.temp.cleanup()
 def test_cron_parser(self):
  dt=datetime(2026,8,21,19,0,tzinfo=timezone.utc);self.assertTrue(cron_matches("0 19 * * *",dt));self.assertFalse(cron_matches("1 19 * * *",dt))
 def test_event_cursor_and_idempotency(self):
  self.repo.put_rule({"rule_id":"event-w","trigger":{"type":"event","event_type":"INSTANCE_DRIFT_DETECTED"},"actions":[{"type":"broadcast","broadcast":{"scope":"instance","target":"instance-w","message":"drift"}}]})
  events=UniversalEventRepository(self.backend);events.initialize();events.publish({"event_id":"11111111-1111-4111-8111-111111111111","event_type":"INSTANCE_DRIFT_DETECTED","source":"test","instance_id":"instance-w","agent_id":"agent-w","data":{}})
  self.assertEqual(self.worker.process_events(),1);self.assertEqual(len(self.repo.list_broadcasts()),1);self.assertEqual(self.worker.process_events(),0);self.assertEqual(len(self.repo.list_broadcasts()),1)
 def test_schedule_minute_is_idempotent(self):
  self.repo.put_rule({"rule_id":"schedule-w","trigger":{"type":"schedule","expression":"0 19 * * *"},"actions":[{"type":"broadcast","broadcast":{"scope":"instance","target":"instance-w","message":"scheduled"}}]})
  dt=datetime(2026,8,21,19,0,tzinfo=timezone.utc);self.assertEqual(self.worker.process_schedules(dt),1);self.assertEqual(self.worker.process_schedules(dt),0);self.assertEqual(len(self.repo.list_broadcasts()),1)
if __name__=="__main__":unittest.main()
