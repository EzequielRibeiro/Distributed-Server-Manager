#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard",ROOT/"agents"/"linux"/"runtime"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_heartbeat_api import record_agent_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from content_platform import ContentValidationError,normalize_assignment
from content_repository import ContentRepository
from content_client import _safe_target

class ContentContractTest(unittest.TestCase):
 def test_checksum_and_isolated_default_target(self):
  raw={"agent_id":"agent-c4","instance_id":"instance-c4","content_id":"mod-one","game_id":"minecraft","content_type":"mod","provider":"http","artifact":{"url":"https://example.invalid/mod.jar"}}
  one=normalize_assignment(raw);two=normalize_assignment(raw)
  self.assertEqual(one["checksum"],two["checksum"]);self.assertEqual(one["target"],"mods/mod-one");self.assertEqual(one["kind"],"CapivaraContentAssignment")
 def test_rejects_paths_identity_and_shell(self):
  base={"agent_id":"agent-c4","instance_id":"instance-c4","content_id":"mod-one","game_id":"minecraft","provider":"http"}
  with self.assertRaises(ContentValidationError):normalize_assignment({**base,"target":"../outside"})
  with self.assertRaises(ContentValidationError):normalize_assignment({**base,"artifact":{"command":"rm -rf /"}})
  with self.assertRaises(ContentValidationError):normalize_assignment(base,expected_agent_id="agent-other")
 def test_agent_target_is_confined(self):
  root=Path("/tmp/instance")
  self.assertEqual(_safe_target(root,"mods/example"),Path("/tmp/instance/content/mods/example"))
  with self.assertRaises(ValueError):_safe_target(root,"../../etc")

class ContentRepositoryTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"capivara.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-controller","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-agent","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-c4","node-controller","C4"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-c4","controller-c4","node-agent","Agent C4","active"));c.execute("INSERT INTO customers(id,controller_id,name) VALUES (?,?,?)",("customer-c4","controller-c4","Customer C4"));c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-c4","node-agent","minecraft","C4 Instance","stopped","controller-c4","agent-c4","customer-c4"))
  self.repo=ContentRepository(self.backend);self.repo.initialize()
 def tearDown(self):self.backend.close();self.tmp.cleanup()
 def payload(self,version="1.0",state="installed"):
  return {"instance_id":"instance-c4","content_id":"mod-one","game_id":"minecraft","content_type":"mod","desired_state":state,"version":version,"provider":"http","artifact":{"url":"https://example.invalid/mod-one.jar","sha256":"0"*64}}
 def test_revision_history_and_noop(self):
  first=self.repo.put(self.payload(),requested_by="test");same=self.repo.put(self.payload(),requested_by="test");second=self.repo.put(self.payload("2.0"),requested_by="test")
  self.assertTrue(first["changed"]);self.assertFalse(same["changed"]);self.assertEqual(second["assignment"]["revision"],2);self.assertEqual([r["revision"] for r in self.repo.history(first["assignment"]["assignment_id"])],[2,1])
 def test_heartbeat_delivers_and_ack_suppresses_replay(self):
  stored=self.repo.put(self.payload())["assignment"];first=record_agent_heartbeat("agent-c4",{"agent_id":"agent-c4"},backend=self.backend);self.assertEqual(first["content_count"],1);cmd=first["content_commands"][0];self.assertEqual(cmd["assignment_id"],stored["assignment_id"])
  report={"instance_id":"instance-c4","content_id":"mod-one","desired_revision":cmd["revision"],"applied_revision":cmd["revision"],"desired_checksum":cmd["checksum"],"applied_checksum":cmd["checksum"],"status":"applied","installed_version":"1.0"}
  second=record_agent_heartbeat("agent-c4",{"agent_id":"agent-c4","content_state":[report]},backend=self.backend);self.assertEqual(second["content_count"],0)
 def test_spoofed_or_unknown_instance_is_rejected(self):
  with self.assertRaises(ContentValidationError):self.repo.put({**self.payload(),"instance_id":"missing"})
  accepted=self.repo.record_agent_state("agent-c4",[{"instance_id":"missing","content_id":"mod","desired_revision":1,"desired_checksum":"x","status":"applied"}]);self.assertEqual(accepted,0)

if __name__=="__main__":unittest.main()
