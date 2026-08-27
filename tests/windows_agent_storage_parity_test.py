from __future__ import annotations
from contextlib import nullcontext
import importlib,os,sys,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"windows"/"runtime"
class WindowsAgentStorageParityTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.state=self.root/"state";self.config_path=self.root/"agent.json";os.environ["PROGRAMDATA"]=str(self.root);os.environ["CAPIVARA_AGENT_STATE_DIR"]=str(self.state);os.environ["CAPIVARA_AGENT_CONFIG"]=str(self.config_path)
  if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
  for name in ("storage_pools","configuration_client","runtime_metrics","queue_observability","storage_pool_migration_state","storage_pool_migration_client","storage_pool_migration_executor","instance_runtime","runtime_materialization"):
   sys.modules.pop(name,None)
  self.storage=importlib.import_module("storage_pools");self.instance_runtime=importlib.import_module("instance_runtime");self.executor=importlib.import_module("storage_pool_migration_executor");self.client=importlib.import_module("storage_pool_migration_client");self.metrics=importlib.import_module("runtime_metrics");self.configuration=importlib.import_module("configuration_client")
  self.source=self.root/"source";self.target=self.root/"target";self.source.mkdir();self.target.mkdir();self.config={"agent_id":"agent-win","storage_pools":[{"id":"source","root_path":str(self.source),"enabled":True,"storage_class":"capacity","priority":10},{"id":"target","root_path":str(self.target),"enabled":True,"storage_class":"nvme","priority":100,"reserve_bytes":1}],"default_storage_pool_id":"source"};self.config_path.write_text(__import__("json").dumps(self.config),encoding="utf-8")
 def tearDown(self):self.temp.cleanup()
 def test_storage_pool_policy_and_inventory(self):
  pools=self.storage.storage_pools(self.config);self.assertEqual([x["id"] for x in pools],["source","target"]);self.assertEqual(self.storage.default_storage_pool_id(self.config),"source");inventory=self.storage.pool_inventory(self.config);self.assertEqual(len(inventory),2);self.assertTrue(all(x["health"]=="online" for x in inventory));self.assertEqual(next(x for x in inventory if x["id"]=="target")["usable_bytes"],next(x for x in inventory if x["id"]=="target")["free_bytes"]-1)
 def test_managed_configuration_applies_storage_pools_to_agent_json(self):
  command={"target_type":"agent","target_id":"agent-win","namespace":"capivara.agent.storage","revision":"r1","checksum":"sha256:test","value":{"storage_pools":[{"id":"target","root_path":str(self.target),"enabled":True,"storage_class":"nvme","priority":200}],"default_storage_pool_id":"target"}}
  report=self.configuration.apply_configuration(command);self.assertEqual(report["status"],"applied");saved=__import__("json").loads(self.config_path.read_text(encoding="utf-8"));self.assertEqual(saved["default_storage_pool_id"],"target");self.assertEqual(saved["storage_pools"][0]["id"],"target")
 def test_metrics_publish_storage_pool_and_queue_health(self):
  payload=self.metrics.snapshot(queue_depth={"storage_pool_migrations":1});self.assertEqual({x["id"] for x in payload["storage_pools"]},{"source","target"});self.assertIn("queue_health",payload);self.assertIn("storage_pool_migrations",payload["queue_health"]);names={x["metric_name"] for x in payload["observability_samples"]};self.assertIn("capivara.storage.pool.usable_bytes",names);self.assertIn("capivara.storage.pool.health",names)
 def _record(self,pool="source"):
  root=(self.source if pool=="source" else self.target)/"instance-one";return {"instance_id":"instance-one","agent_id":"agent-win","storage_pool_id":pool,"instance_state_root":str(root),"working_directory":str(self.root/"serverfiles"),"path":str(self.root/"serverfiles"),"executable":str(self.root/"serverfiles"/"server.exe"),"runtime_id":"runtime-one","adapter":"windows-process","arguments":[],"environment":{},"desired_state":"stopped"}
 def test_migration_copies_verifies_switches_and_preserves_source(self):
  src=self.source/"instance-one";src.mkdir();(src/"a.cfg").write_bytes(b"abc");record=self._record("source");registered=[];command={"migration_id":"migration-one","agent_id":"agent-win","instance_id":"instance-one","source_storage_pool_id":"source","target_storage_pool_id":"target","action":"migrate"};result_path=self.root/"result.json"
  with patch.object(self.executor.instance_runtime,"_owned",return_value=record),patch.object(self.executor.instance_runtime,"status",return_value={"observed_state":"stopped"}),patch.object(self.executor,"runtime_operation",return_value=nullcontext()),patch.object(self.executor,"emit_runtime_event",return_value={}),patch.object(self.executor.runtime_materialization,"materialize",return_value={}),patch.object(self.executor.instance_runtime,"register_instance",side_effect=lambda value:registered.append(dict(value)) or value):result=self.executor.execute(self.config,command,result_path)
  self.assertEqual(result["status"],"completed");self.assertTrue((self.source/"instance-one"/"a.cfg").exists());self.assertEqual((self.target/"instance-one"/"a.cfg").read_bytes(),b"abc");self.assertEqual(registered[-1]["storage_pool_id"],"target");self.assertEqual(result["verified_bytes"],3)
 def test_cleanup_only_removes_preserved_source_after_target_switch(self):
  src=self.source/"instance-one";dst=self.target/"instance-one";src.mkdir();dst.mkdir();(src/"a.cfg").write_bytes(b"abc");(dst/"a.cfg").write_bytes(b"abc");record=self._record("target");command={"migration_id":"cleanup-one","source_migration_id":"migration-one","agent_id":"agent-win","instance_id":"instance-one","source_storage_pool_id":"source","target_storage_pool_id":"target","action":"cleanup-source","verified_files":1,"verified_bytes":3};result_path=self.root/"cleanup.json"
  with patch.object(self.executor.instance_runtime,"_owned",return_value=record),patch.object(self.executor,"runtime_operation",return_value=nullcontext()),patch.object(self.executor,"emit_runtime_event",return_value={}):result=self.executor.execute(self.config,command,result_path)
  self.assertEqual(result["status"],"completed");self.assertFalse(src.exists());self.assertTrue(dst.exists())
 def test_cleanup_rejects_symlink_and_wrong_runtime_pool(self):
  src=self.source/"instance-one";dst=self.target/"instance-one";src.mkdir();dst.mkdir();record=self._record("source");command={"migration_id":"cleanup-two","agent_id":"agent-win","instance_id":"instance-one","source_storage_pool_id":"source","target_storage_pool_id":"target","action":"cleanup-source"}
  with patch.object(self.executor.instance_runtime,"_owned",return_value=record),patch.object(self.executor,"runtime_operation",return_value=nullcontext()),patch.object(self.executor,"emit_runtime_event",return_value={}):result=self.executor.execute(self.config,command,self.root/"wrong.json")
  self.assertEqual(result["status"],"failed");self.assertTrue(src.exists())
  record=self._record("target")
  try:(src/"unsafe").symlink_to(self.root/"outside")
  except (OSError,NotImplementedError):return
  with patch.object(self.executor.instance_runtime,"_owned",return_value=record),patch.object(self.executor,"runtime_operation",return_value=nullcontext()),patch.object(self.executor,"emit_runtime_event",return_value={}):result=self.executor.execute(self.config,command,self.root/"link.json")
  self.assertEqual(result["status"],"failed");self.assertTrue(src.exists())
 def test_cleanup_staging_maps_controller_verification_fields(self):
  command={"migration_id":"cleanup-three","instance_id":"instance-one","action":"cleanup-source","expected_verified_files":7,"expected_verified_bytes":99};captured={}
  class Dummy:
   pass
  with patch.object(self.client,"paths",return_value=(self.root/"req.json",self.root/"res.json",self.root/"log.txt")),patch.object(self.client,"read_json",return_value=None),patch.object(self.client,"write_json",side_effect=lambda path,value:captured.setdefault(path.name,dict(value))),patch.object(self.client.subprocess,"Popen",return_value=Dummy()):self.client.stage_storage_pool_migration(command,config_path=self.config_path)
  self.assertEqual(captured["req.json"]["verified_files"],7);self.assertEqual(captured["req.json"]["verified_bytes"],99)
if __name__=="__main__":unittest.main()
