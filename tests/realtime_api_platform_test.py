#!/usr/bin/env python3
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from api_access_repository import ApiAccessRepository
from api_platform import ApiValidationError,decode_cursor,encode_cursor,normalize_scopes
from backend import DatabaseConfig
from backend_factory import create_backend
from realtime_http import API_EVENTS_PATH,API_INSTANCES_PATH,API_STATUS_PATH,dispatch_realtime_get
from realtime_repository import RealtimeRepository
from universal_event_repository import UniversalEventRepository

class D2ContractsTest(unittest.TestCase):
 def test_scopes_and_cursor(self):
  self.assertEqual(decode_cursor(encode_cursor("2026-08-21T12:00:00Z","evt-1")),("2026-08-21T12:00:00Z","evt-1"))
  self.assertIn("events:read",normalize_scopes(None))
  with self.assertRaises(ApiValidationError):normalize_scopes(["shell:exec"])
  with self.assertRaises(ApiValidationError):decode_cursor("not-a-cursor")

class D2RepositoryTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.temp.name)/"d2.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("controller-node","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-d2","controller-node","D2"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-d2","controller-d2","agent-node","Agent D2","active"));c.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",("customer-d2","controller-d2","Customer","active"));c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-d2","agent-node","game.generic","Generic","offline","controller-d2","agent-d2","customer-d2"))
  self.tokens=ApiAccessRepository(self.backend);self.tokens.initialize();self.events=UniversalEventRepository(self.backend);self.events.initialize()
 def tearDown(self):self.backend.close();self.temp.cleanup()
 def test_token_is_one_time_secret_and_revocable(self):
  created=self.tokens.create_token(name="integration",scopes=["events:read","realtime:read"]);presented=created["token"]
  self.assertTrue(presented.startswith("capv2_"));listed=self.tokens.list_tokens();self.assertNotIn("token",listed[0]);self.assertNotIn("secret_hash",listed[0])
  principal=self.tokens.authenticate(presented);self.assertEqual(principal["principal_type"],"api_token");self.assertIn("events:read",principal["scopes"])
  self.tokens.revoke(created["token_id"])
  with self.assertRaises(PermissionError):self.tokens.authenticate(presented)
 def test_cursor_order_and_public_rbac(self):
  for n in range(3):self.events.publish({"event_id":f"00000000-0000-4000-8000-00000000000{n}","event_type":"D2_TEST","occurred_at":f"2026-08-21T12:00:0{n}Z","source":"test","agent_id":"agent-d2","instance_id":"instance-d2","data":{"n":n}})
  principal={"token_id":"x","scopes":["events:read","realtime:read","instances:read"]}
  status,page=dispatch_realtime_get(API_EVENTS_PATH,"limit=2",principal=principal,backend=self.backend);self.assertEqual(status,200);self.assertEqual(page["count"],2);self.assertTrue(page["has_more"])
  status,page2=dispatch_realtime_get(API_EVENTS_PATH,"cursor="+page["cursor"],principal=principal,backend=self.backend);self.assertEqual(status,200);self.assertEqual(page2["count"],1);self.assertEqual(page2["events"][0]["data"]["n"],2)
  status,body=dispatch_realtime_get(API_STATUS_PATH,"",principal={"scopes":["events:read"]},backend=self.backend);self.assertEqual(status,403)
  status,body=dispatch_realtime_get(API_INSTANCES_PATH,"",principal=principal,backend=self.backend);self.assertEqual(status,200);self.assertEqual(body["instances"][0]["id"],"instance-d2")

if __name__=="__main__":unittest.main()
