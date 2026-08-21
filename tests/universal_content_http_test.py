#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from backend import DatabaseConfig
from backend_factory import create_backend
from content_http import CONTENT_PATH,dispatch_content_get,dispatch_content_post
class ContentHttpTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"db.sqlite")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("ctrl-node","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("ctrl","ctrl-node","Controller"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent","ctrl","agent-node","Agent","active"));c.execute("INSERT INTO customers(id,controller_id,name) VALUES (?,?,?)",("cust","ctrl","Customer"));c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("inst","agent-node","minecraft","Instance","stopped","ctrl","agent","cust"))
 def tearDown(self):self.backend.close();self.tmp.cleanup()
 def test_admin_create_list_and_event(self):
  payload={"instance_id":"inst","content_id":"plugin-a","game_id":"minecraft","content_type":"plugin","provider":"http","artifact":{"url":"https://example.invalid/plugin.jar"}}
  status,body=dispatch_content_post(CONTENT_PATH,payload,user={"role":"admin","username":"root"},backend=self.backend);self.assertEqual(status,200);self.assertTrue(body["changed"])
  status,body=dispatch_content_get(CONTENT_PATH,"instance_id=inst",user={"role":"controller","username":"operator"},backend=self.backend);self.assertEqual(status,200);self.assertEqual(body["count"],1)
  with self.backend.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM universal_events WHERE event_type='CONTENT_ASSIGNMENT_UPDATED'").fetchone()[0],1)
 def test_customer_is_forbidden(self):
  status,_=dispatch_content_get(CONTENT_PATH,"",user={"role":"customer","username":"customer"},backend=self.backend);self.assertEqual(status,403)
if __name__=="__main__":unittest.main()
