import sys,tempfile,unittest,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/"database";CORE=ROOT/"core"
for p in (str(DB),str(CORE)):
 if p not in sys.path:sys.path.insert(0,p)
from backend import DatabaseConfig
from backends.sqlite_backend import SQLiteBackend
from federation import FederationController,FederationPlacementRequest,FederationRoute,build_event_batch,build_inventory_snapshot,select_controller,validate_inventory_snapshot
from federation_repository import FederationRepository

class FakeEvents:
 def __init__(self):self.items={}
 def publish(self,event):
  eid=event["event_id"];created=eid not in self.items;self.items[eid]=dict(event);return {"event":self.items[eid],"created":created}
 def list_events(self,limit=100):return list(self.items.values())[-limit:]

class FederationContractTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=SQLiteBackend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"capivara.db")));self.repo=FederationRepository(self.backend);self.repo.initialize()
 def tearDown(self):self.tmp.cleanup()
 def ctl(self,cid,dc="sp",region="br-se",status="online",priority=100):return FederationController(cid,f"https://{cid}.example",region,dc,"datacenter",status,priority)
 def test_controller_requires_https(self):
  with self.assertRaises(ValueError):FederationController("dc-a","http://dc-a.example",datacenter_id="dc-a").validate()
 def test_snapshot_is_bounded_and_strips_unapproved_secret_fields(self):
  snap=build_inventory_snapshot(controller_id="controller-sp",sequence=7,agents=[{"agent_id":"a1","datacenter_id":"sp","status":"active","token":"secret"}],instances=[{"instance_id":"i1","agent_id":"a1","game_id":"dayz","customer_id":"c1","password":"secret"}]);payload=validate_inventory_snapshot(snap,"controller-sp");self.assertNotIn("token",payload["agents"][0]);self.assertNotIn("password",payload["instances"][0])
 def test_nested_secret_in_capacity_fails_closed(self):
  with self.assertRaises(ValueError):build_inventory_snapshot(controller_id="c1",sequence=1,capacity={"meta":{"secret":"x"}})
 def test_route_prefers_datacenter_then_priority(self):
  cs=[self.ctl("sp-a",priority=20),self.ctl("sp-b",priority=10)];rs=[FederationRoute("datacenter","sp","sp-a",5),FederationRoute("datacenter","sp","sp-b",10)];self.assertEqual(select_controller(cs,rs,region_id="br-se",datacenter_id="sp").controller_id,"sp-a")
 def test_offline_controller_is_never_selected(self):self.assertIsNone(select_controller([self.ctl("sp-a",status="offline")],[FederationRoute("datacenter","sp","sp-a")],datacenter_id="sp"))
 def test_registry_credentials_nonce_replay_and_snapshot_sequence(self):
  self.repo.upsert_controller(self.ctl("sp-a",status="pending"));cred=self.repo.issue_credential("sp-a");ts=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");nonce="nonce-0123456789abcdef";p=self.repo.authenticate_peer(cred["token"],request_timestamp=ts,nonce=nonce);self.assertEqual(p["controller_id"],"sp-a")
  with self.assertRaises(PermissionError):self.repo.authenticate_peer(cred["token"],request_timestamp=ts,nonce=nonce)
  s1=build_inventory_snapshot(controller_id="sp-a",sequence=1,capacity={"agents":2});self.assertTrue(self.repo.store_snapshot("sp-a",s1)["created"]);self.assertFalse(self.repo.store_snapshot("sp-a",s1)["created"])
  with self.assertRaises(ValueError):self.repo.store_snapshot("sp-a",build_inventory_snapshot(controller_id="sp-a",sequence=0))
 def test_stale_authentication_fails(self):
  self.repo.upsert_controller(self.ctl("sp-a",status="pending"));cred=self.repo.issue_credential("sp-a");old=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat().replace("+00:00","Z")
  with self.assertRaises(ValueError):self.repo.authenticate_peer(cred["token"],request_timestamp=old,nonce="nonce-0123456789abcdef")
 def test_global_inventory_and_handoff_are_idempotent(self):
  for cid,dc in (("sp-a","sp"),("rj-a","rj")):
   self.repo.upsert_controller(self.ctl(cid,dc=dc));self.repo.store_snapshot(cid,build_inventory_snapshot(controller_id=cid,sequence=1,agents=[{"agent_id":cid+"-agent","datacenter_id":dc,"status":"active"}],capacity={"agents":1}))
  inv=self.repo.global_inventory();self.assertEqual(inv["capacity"]["agents"],2.0);self.repo.upsert_route(FederationRoute("datacenter","sp","sp-a",1));req=FederationPlacementRequest("req-1","instance-1","minecraft",region_id="br-se",datacenter_id="sp");one=self.repo.create_handoff(req);two=self.repo.create_handoff(req);self.assertEqual(one["handoff_id"],two["handoff_id"])
 def test_event_federation_deduplicates_and_rejects_conflicting_replay(self):
  self.repo.upsert_controller(self.ctl("sp-a"));events=FakeEvents();eid=str(uuid.uuid4());event={"event_id":eid,"event_type":"INSTANCE_STARTED","source":"federation.test","occurred_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"severity":"info","data":{}}
  batch=build_event_batch("sp-a",1,[event]);first=self.repo.ingest_event_batch("sp-a",batch,events);second=self.repo.ingest_event_batch("sp-a",batch,events);self.assertEqual(first["created"],1);self.assertEqual(second["created"],0)
  altered=dict(event);altered["data"]={"different":True}
  with self.assertRaises(ValueError):self.repo.ingest_event_batch("sp-a",2,build_event_batch("sp-a",2,[altered]),events)

if __name__=="__main__":unittest.main()
