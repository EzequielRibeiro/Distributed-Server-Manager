#!/usr/bin/env python3
from __future__ import annotations
import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard",ROOT/"agents"/"linux"/"runtime"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_heartbeat_api import record_agent_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from content_platform import ContentValidationError,normalize_assignment
from content_repository import ContentRepository
import content_client
from content_client import _safe_target
from content_update_provider import detect_content_update,parse_workshop_manifest,parse_workshop_package

class _Response:
 def __init__(self,payload):self.payload=json.dumps(payload).encode("utf-8")
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self):return self.payload

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
 def test_running_instance_rolls_back_content_when_readiness_fails(self):
  with tempfile.TemporaryDirectory() as td:
   instance=Path(td)/"instance";target=instance/"content"/"mods"/"mod-one";target.mkdir(parents=True);(target/"old.bin").write_text("old",encoding="utf-8")
   source=Path(td)/"new.bin";source.write_text("new",encoding="utf-8")
   cmd={"instance_id":"instance-c4","content_id":"mod-one","target":"mods/mod-one","provider":"local","artifact":{"filename":"new.bin"}}
   lifecycle=[]
   def life(config,iid,action):lifecycle.append(action);return {"observed_state":"stopped" if action=="stop" else "running"}
   with patch.object(content_client,"_owned",return_value=({"instance_id":"instance-c4","agent_id":"agent-c4"},instance)),patch.object(content_client,"_source",return_value=source),patch.object(content_client.instance_runtime,"status",return_value={"observed_state":"running"}),patch.object(content_client.instance_runtime,"lifecycle",side_effect=life),patch.object(content_client.instance_runtime,"doctor",side_effect=[{"ready":False},{"ready":True}]):
    with self.assertRaises(content_client.ContentActivationError):content_client._install({"agent_id":"agent-c4"},cmd)
   self.assertTrue((target/"old.bin").is_file());self.assertFalse((target/"new.bin").exists());self.assertEqual(lifecycle,["stop","start","stop","start"]);self.assertFalse(target.with_name(target.name+".c4-old").exists())
 def test_windows_content_client_has_same_readiness_contract(self):
  text=(ROOT/"agents/windows/runtime/content_client.py").read_text(encoding="utf-8")
  for marker in ("instance_runtime.lifecycle","instance_runtime.doctor","ContentRollbackError",".c4-old","unfinished content transaction detected","package_id","content_type"):self.assertIn(marker,text)
 def test_safe_source_metadata_keeps_workshop_identity_without_full_artifact(self):
  meta=content_client._source_metadata({"provider":"steam","content_type":"workshop","game_id":"example","target":"workshop/item","artifact":{"provider":"steam","package_id":"221100:123456","resolved_path":"example/item","download_url":"https://secret.invalid/x"}})
  self.assertEqual(meta["package_id"],"221100:123456");self.assertEqual(meta["provider"],"steam");self.assertEqual(meta["content_type"],"workshop");self.assertNotIn("download_url",meta);self.assertNotIn("resolved_path",meta)
 def test_workshop_detector_compares_local_and_remote_revision(self):
  self.assertEqual(parse_workshop_package("221100:123456"),("221100","123456"))
  manifest='''"AppWorkshop"\n{\n "WorkshopItemDetails"\n {\n  "123456"\n  {\n   "timeupdated" "100"\n  }\n }\n}'''
  self.assertEqual(parse_workshop_manifest(manifest,"123456"),"100")
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);path=root/"tools/steamcmd/steamapps/workshop/appworkshop_221100.acf";path.parent.mkdir(parents=True);path.write_text(manifest,encoding="utf-8")
   def opener(request,timeout=30):return _Response({"response":{"publishedfiledetails":[{"time_updated":101}]}})
   detail=detect_content_update({"provider":"steam","content_type":"workshop","package_id":"221100:123456"},root,opener=opener,force_refresh=True)
   self.assertEqual(detail["state"],"update_available");self.assertEqual(detail["installed_revision"],"100");self.assertEqual(detail["available_revision"],"101");self.assertTrue(detail["rollback_supported"])
 def test_non_workshop_content_detector_fails_closed(self):
  detail=detect_content_update({"provider":"http","content_type":"mod","package_id":"x"},Path("/tmp"));self.assertFalse(detail["detector_supported"]);self.assertEqual(detail["state"],"unsupported")
 def test_update_inventory_is_game_neutral_and_windows_parity_exists(self):
  for rel in ("agents/linux/runtime/content_update_provider.py","agents/linux/runtime/content_update_inventory.py","agents/windows/runtime/content_update_provider.py","agents/windows/runtime/content_update_inventory.py"):
   text=(ROOT/rel).read_text(encoding="utf-8").lower()
   for game in ("dayz","projectzomboid","arma3","rust","minecraft"):self.assertNotIn(game,text)
  windows_metrics=(ROOT/"agents/windows/runtime/runtime_metrics.py").read_text(encoding="utf-8");linux_metrics=(ROOT/"agents/linux/runtime/runtime_metrics.py").read_text(encoding="utf-8")
  self.assertIn('content_updates',windows_metrics);self.assertIn('content_updates',linux_metrics)

class ContentRepositoryTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"capivara.db")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-controller","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-agent","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-c4","node-controller","C4"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-c4","controller-c4","node-agent","Agent C4","active"));customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller-c4","Customer C4"));customer_id=int(customer.lastrowid);c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-c4","node-agent","minecraft","C4 Instance","stopped","controller-c4","agent-c4",customer_id))
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
