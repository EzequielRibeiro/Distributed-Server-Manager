#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard",ROOT/"agents"/"linux"/"runtime"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_heartbeat_api import record_agent_heartbeat
from automation_engine import AutomationEngine
from automation_http import dispatch_automation_get,dispatch_automation_post
from automation_platform import AutomationValidationError,normalize_broadcast,normalize_rule
from automation_repository import AutomationRepository
from backend import DatabaseConfig
from backend_factory import create_backend
class D1ContractTest(unittest.TestCase):
 def test_rule_and_broadcast_are_deterministic(self):
  raw={"rule_id":"maintenance","trigger":{"type":"event","event_type":"BACKUP_COMPLETED"},"actions":[{"type":"broadcast","broadcast":{"scope":"global","message":"Concluído"}}]}
  one=normalize_rule(raw);two=normalize_rule(raw);self.assertEqual(one["checksum"],two["checksum"]);self.assertEqual(one["kind"],"CapivaraAutomationRule")
  self.assertEqual(normalize_broadcast({"scope":"global","message":"hello"})["kind"],"CapivaraBroadcast")
 def test_contract_rejects_shell_and_invalid_scope(self):
  with self.assertRaises(AutomationValidationError):normalize_broadcast({"scope":"shell","message":"x"})
  with self.assertRaises(AutomationValidationError):normalize_rule({"rule_id":"x","trigger":{"type":"event","event_type":"X"},"actions":[]})
class D1RepositoryTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.temp.name)/"d1.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("controller-node","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-d1","controller-node","D1"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-d1","controller-d1","agent-node","Agent D1","active"));customer=c.execute("INSERT INTO customers(controller_id,name,status) VALUES (?,?,?)",("controller-d1","Customer","active"));customer_id=int(customer.lastrowid);c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-d1","agent-node","game.generic","Generic","offline","controller-d1","agent-d1",customer_id))
  self.repo=AutomationRepository(self.backend);self.repo.initialize()
 def tearDown(self):self.backend.close();self.temp.cleanup()
 def rule(self,message="maintenance"):
  return {"rule_id":"rule-d1","name":"Rule D1","trigger":{"type":"event","event_type":"INSTANCE_DRIFT_DETECTED"},"conditions":[{"field":"instance_id","operator":"==","value":"instance-d1"}],"actions":[{"type":"broadcast","broadcast":{"scope":"instance","target":"instance-d1","message":message,"priority":"high","ttl_seconds":600}}]}
 def test_rule_revision_noop_and_event_fire(self):
  first=self.repo.put_rule(self.rule(),requested_by="test");same=self.repo.put_rule(self.rule(),requested_by="test");second=self.repo.put_rule(self.rule("changed"),requested_by="test")
  self.assertTrue(first["changed"]);self.assertFalse(same["changed"]);self.assertEqual(second["rule"]["revision"],2);self.assertEqual(len(self.repo.history("rule-d1")),2)
  runs=AutomationEngine(self.backend).fire("event",{"event_type":"INSTANCE_DRIFT_DETECTED","instance_id":"instance-d1"},trigger_ref="event-1",requested_by="test");self.assertEqual(len(runs),1);self.assertEqual(runs[0]["status"],"completed");self.assertEqual(len(self.repo.list_broadcasts()),1)
 def test_broadcast_scopes_delivery_ack_and_retry_boundary(self):
  item=self.repo.create_broadcast({"scope":"global","message":"Global","require_ack":True},requested_by="test");self.assertEqual(item["recipients"],1)
  commands=self.repo.desired_for_agent("agent-d1");self.assertEqual(len(commands),1);delivery=commands[0]
  self.assertEqual(self.repo.record_broadcast_state("wrong-agent",[{"delivery_id":delivery["delivery_id"],"status":"acknowledged"}]),0)
  result=record_agent_heartbeat("agent-d1",{"agent_id":"agent-d1","broadcast_state":[{"delivery_id":delivery["delivery_id"],"status":"acknowledged"}]},backend=self.backend);self.assertEqual(result["broadcast_count"],0)
 def test_http_rbac_and_manual_broadcast(self):
  admin={"role":"admin","username":"root"};status,body=dispatch_automation_post("/api/broadcasts",{"scope":"instance","target":"instance-d1","message":"hello"},user=admin,backend=self.backend);self.assertEqual(status,201);self.assertEqual(body["recipients"],1)
  status,body=dispatch_automation_get("/api/broadcasts","",user=admin,backend=self.backend);self.assertEqual(status,200);self.assertEqual(body["count"],1)
  status,_=dispatch_automation_get("/api/automation","",user={"role":"customer"},backend=self.backend);self.assertEqual(status,403)
if __name__=="__main__":unittest.main()
