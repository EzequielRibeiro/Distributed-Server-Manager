#!/usr/bin/env python3
from __future__ import annotations
import os,subprocess,sys,tempfile,textwrap,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];WINDOWS_RUNTIME=ROOT/"agents"/"windows"/"runtime"
class WindowsAgentRuntimeParityTest(unittest.TestCase):
 def _run(self,source,*,state_dir=None):
  env=os.environ.copy();env["PYTHONPATH"]=str(WINDOWS_RUNTIME)
  if state_dir:
   env["CAPIVARA_AGENT_STATE_DIR"]=state_dir;env["CAPIVARA_BACKUP_ROOT"]=str(Path(state_dir)/"backups");env["CAPIVARA_AGENT_GAME_DATA_ROOT"]=str(Path(state_dir)/"game-data")
  return subprocess.run([sys.executable,"-c",textwrap.dedent(source)],cwd=str(ROOT),env=env,capture_output=True,text=True,check=False)
 def test_instance_command_contract_and_operation_journal(self):
  with tempfile.TemporaryDirectory() as state:
   r=self._run('''
import instance_runtime
class FakeAdapter:
 name="fake"
 def status(self,i):return {"available":True,"active_state":"inactive"}
 def start(self,i):return {"action":"start","state":{"available":True,"active_state":"active"}}
 def stop(self,i):return {"action":"stop","state":{"available":True,"active_state":"inactive"}}
 def restart(self,i):return {"action":"restart","state":{"available":True,"active_state":"active"}}
 def doctor(self,i):return {"ready":True,"findings":[]}
instance_runtime.resolve_adapter=lambda record:FakeAdapter();config={"agent_id":"win-agent-one"}
instance_runtime.register_instance({"instance_id":"srv-one","agent_id":"win-agent-one","game_id":"generic-game","runtime_id":"CapivaraInstance-srv-one","adapter":"fake"})
cmd={"command_id":"cmd-start","instance_id":"srv-one","action":"start"};first=instance_runtime.handle_command(config,cmd);second=instance_runtime.handle_command(config,cmd)
assert first==second and first["status"]=="completed" and first["result"]["observed_state"]=="running"
assert instance_runtime.inventory(config)[0]["instance_id"]=="srv-one";assert instance_runtime.read_result()["command_id"]=="cmd-start"
from runtime_operations import read_operation
assert read_operation("srv-one")["status"]=="completed"
instance_runtime.clear_result("cmd-start");assert instance_runtime.read_result() is None
''',state_dir=state);self.assertEqual(r.returncode,0,r.stderr)
 def test_configuration_backup_broadcast_events_and_reconciliation(self):
  with tempfile.TemporaryDirectory() as state:
   r=self._run('''
from pathlib import Path
import instance_runtime,runtime_reconciler
from configuration_client import apply_configuration_commands,configuration_state
from backup_client import apply_backup_commands
import broadcast_client
from runtime_events import emit_runtime_event,read_runtime_events,acknowledge_runtime_events
class BroadcastAdapter:
 name="broadcast-test"
 def broadcast(self,i,message,priority="normal"):return {"message":message,"priority":priority}
config={"agent_id":"win-agent-one"};root=Path(instance_runtime.STATE_DIR)/"instance-workspaces"/"srv-one";root.mkdir(parents=True);exe=root/"server.exe";exe.write_bytes(b"test");(root/"server.txt").write_text("ok")
instance_runtime.register_instance({"instance_id":"srv-one","agent_id":"win-agent-one","runtime_id":"srv-one","adapter":"windows-process","path":str(root),"working_directory":str(root),"executable":str(exe),"arguments":[],"environment":{},"desired_state":"stopped","observed_state":"stopped"})
apply_configuration_commands([{"target_type":"instance","target_id":"srv-one","namespace":"server","revision":"1","checksum":"abc","value":{"slots":10}}]);assert configuration_state()[0]["status"]=="applied"
backup=apply_backup_commands(config,[{"command_id":"backup-1","instance_id":"srv-one","action":"create","policy":{"mode":"full","consistency":"live","compression":"gzip","retention_count":2}}])[0];assert backup["status"]=="completed" and Path(backup["artifact_path"]).is_file()
broadcast_client.resolve_adapter=lambda record:BroadcastAdapter();bcast=broadcast_client.apply_broadcast_commands(config,[{"delivery_id":"delivery-1","broadcast_id":"m1","instance_id":"srv-one","message":"maintenance"}])[0];assert bcast["status"]=="acknowledged"
rec=runtime_reconciler.reconcile_all(config,force=True)[0];assert rec["status"]=="healthy",rec
e=emit_runtime_event(Path(instance_runtime.STATE_DIR),"TEST",agent_id="win-agent-one",instance_id="srv-one");events=read_runtime_events(Path(instance_runtime.STATE_DIR));assert e["event_id"] in {x["event_id"] for x in events};acknowledge_runtime_events(Path(instance_runtime.STATE_DIR),[e["event_id"]]);assert e["event_id"] not in {x["event_id"] for x in read_runtime_events(Path(instance_runtime.STATE_DIR))}
''',state_dir=state);self.assertEqual(r.returncode,0,r.stderr)
 def test_dayz_profile_and_end_to_end_provisioning(self):
  with tempfile.TemporaryDirectory() as state,tempfile.TemporaryDirectory() as install:
   executable=Path(install)/"DayZServer_x64.exe";executable.write_bytes(b"test")
   r=self._run(f'''
from pathlib import Path
import instance_runtime
from provisioning_executor import execute
config={{"agent_id":"win-agent-one"}};request={{"provisioning_id":"p1","instance_id":"srv-dayz","agent_id":"win-agent-one","instance":{{"game_id":"dayz","environment_id":"dayz.stable"}},"desired_state":"stopped","configuration":{{"install_path":{str(install)!r}}},"ports":{{"game":{{"port":2302,"protocol":"udp"}},"game_aux":{{"port":2304,"protocol":"udp"}},"steam_query":{{"port":2305,"protocol":"udp"}}}}}}
result_path=Path(instance_runtime.STATE_DIR)/"provision-result.json";out=execute(config,request,result_path)
assert out["status"]=="completed",out
assert out["runtime"]["adapter"]=="windows-process"
assert out["observed_state"]=="stopped"
record=instance_runtime.get_instance("srv-dayz");assert record["executable"].endswith("DayZServer_x64.exe") and record["desired_state"]=="stopped"
''',state_dir=state);self.assertEqual(r.returncode,0,r.stderr)
 def test_content_desired_state_contract(self):
  with tempfile.TemporaryDirectory() as state:
   r=self._run('''
from pathlib import Path
import instance_runtime
from content_client import apply_content_commands,content_state
config={"agent_id":"win-agent-one"};root=Path(instance_runtime.STATE_DIR)/"instance-workspaces"/"srv-content";root.mkdir(parents=True);source=Path(instance_runtime.STATE_DIR)/"game-data"/"package";source.mkdir(parents=True);(source/"mod.txt").write_text("ok")
instance_runtime.register_instance({"instance_id":"srv-content","agent_id":"win-agent-one","path":str(root)})
cmd={"instance_id":"srv-content","content_id":"mod-one","revision":1,"checksum":"abc","desired_state":"installed","version":"1","provider":"local","target":"mods/mod-one","artifact":{"resolved_path":str(source)}}
report=apply_content_commands(config,[cmd])[0];assert report["status"]=="applied" and (root/"content"/"mods"/"mod-one"/"mod.txt").is_file();assert content_state()[0]["content_id"]=="mod-one"
''',state_dir=state);self.assertEqual(r.returncode,0,r.stderr)
 def test_windows_service_adapter_maps_scm_state(self):
  r=self._run('''
from types import SimpleNamespace
from adapters import windows_service
def fake_run(*args,**kwargs):return SimpleNamespace(returncode=0,stdout="STATE              : 4  RUNNING\\n",stderr="")
windows_service._run=fake_run;status=windows_service.WindowsServiceAdapter().status({"runtime_id":"CapivaraInstance-srv-one"});assert status["available"] and status["active_state"]=="active"
''');self.assertEqual(r.returncode,0,r.stderr)
 def test_windows_agent_heartbeat_exposes_linux_runtime_contract(self):
  source=(WINDOWS_RUNTIME/"agent.py").read_text(encoding="utf-8")
  compact="".join(source.split())
  for token in ('"instances":instance_inventory(config)','"instance_reconciliation":reconciliation_inventory(config)','"instance_runtime_health":health_inventory(config)','"instance_runtime_metrics":runtime_metrics_snapshot','"runtime_events":read_runtime_events','"configuration_state":configuration_state()','"content_state":content_state()','"backup_state":backup_state()','"broadcast_state":broadcast_state()','result.get("provisioning_command")','result.get("game_data_command")','("instance_command","instance_state",handle_instance_command,clear_instance_result,"command_id","instance")','result.get(command_key)'):
   self.assertIn(token,compact)
  self.assertNotIn("runtime_parity",source)
if __name__=="__main__":unittest.main()
