#!/usr/bin/env python3
from __future__ import annotations
import os, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; WINDOWS_RUNTIME=ROOT/"agents"/"windows"/"runtime"
class WindowsAgentRuntimeParityTest(unittest.TestCase):
 def _run(self,source,*,state_dir=None):
  env=os.environ.copy();env["PYTHONPATH"]=str(WINDOWS_RUNTIME)
  if state_dir:env["CAPIVARA_AGENT_STATE_DIR"]=state_dir;env["CAPIVARA_AGENT_BACKUP_DIR"]=str(Path(state_dir)/"backups");env["CAPIVARA_AGENT_GAME_DATA_ROOT"]=str(Path(state_dir)/"game-data")
  return subprocess.run([sys.executable,"-c",textwrap.dedent(source)],cwd=str(ROOT),env=env,capture_output=True,text=True,check=False)
 def test_instance_command_contract_matches_linux_shape(self):
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
instance_runtime.clear_result("cmd-start");assert instance_runtime.read_result() is None
''',state_dir=state);self.assertEqual(r.returncode,0,r.stderr)
 def test_distributed_state_surfaces_and_backup(self):
  with tempfile.TemporaryDirectory() as state:
   r=self._run('''
from pathlib import Path
import instance_runtime, runtime_parity
class FakeAdapter:
 name="fake"
 def status(self,i):return {"available":True,"active_state":"inactive"}
 def start(self,i):return {"state":{"available":True,"active_state":"active"}}
 def stop(self,i):return {"state":{"available":True,"active_state":"inactive"}}
 def restart(self,i):return self.start(i)
 def doctor(self,i):return {"ready":True,"findings":[]}
 def broadcast(self,i,message,priority="normal"):return {"message":message,"priority":priority}
instance_runtime.resolve_adapter=lambda record:FakeAdapter();runtime_parity.resolve_adapter=lambda record:FakeAdapter();config={"agent_id":"win-agent-one"}
root=Path(runtime_parity.STATE_DIR)/"instance-workspaces"/"srv-one";root.mkdir(parents=True);(root/"server.txt").write_text("ok")
instance_runtime.register_instance({"instance_id":"srv-one","agent_id":"win-agent-one","runtime_id":"svc","adapter":"fake","path":str(root),"desired_state":"running","observed_state":"stopped"})
runtime_parity.apply_configuration_commands([{"target_type":"instance","target_id":"srv-one","namespace":"server","revision":"1","checksum":"abc","value":{"slots":10}}])
assert runtime_parity.configuration_state()[0]["status"]=="applied"
backup=runtime_parity.apply_backup_commands(config,[{"instance_id":"srv-one","backup_id":"b1","action":"create"}])[0];assert backup["status"]=="completed" and Path(backup["path"]).is_file()
bcast=runtime_parity.apply_broadcast_commands(config,[{"broadcast_id":"m1","instance_id":"srv-one","message":"maintenance"}])[0];assert bcast["status"]=="completed"
rec=runtime_parity.reconcile_all(config)[0];assert rec["action"]=="start"
e=runtime_parity.emit_runtime_event("TEST",agent_id="win-agent-one",instance_id="srv-one");assert runtime_parity.read_runtime_events();runtime_parity.acknowledge_runtime_events([e["event_id"]]);assert not runtime_parity.read_runtime_events()
''',state_dir=state);self.assertEqual(r.returncode,0,r.stderr)
 def test_provisioning_and_game_data_contracts_exist(self):
  with tempfile.TemporaryDirectory() as state:
   r=self._run('''
import runtime_parity
config={"agent_id":"win-agent-one"};cmd={"provisioning_id":"p1","instance_id":"srv-two","agent_id":"win-agent-one","instance":{"game_id":"generic"},"desired_state":"stopped","runtime":{"adapter":"windows-service","runtime_id":"CapivaraInstance-srv-two"}}
assert runtime_parity.stage_provisioning_command(config,cmd) is True
out=runtime_parity.provisioning_result();assert out["status"]=="completed" and out["runtime"]["adapter"]=="windows-service"
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
  for token in ('"instances":instance_inventory(config)','"instance_reconciliation":reconciliation_inventory(config)','"instance_runtime_health":health_inventory(config)','"instance_runtime_metrics":metrics_snapshot()','"runtime_events":read_runtime_events','"configuration_state":configuration_state()','"content_state":content_state()','"backup_state":backup_state()','"broadcast_state":broadcast_state()','result.get("provisioning_command")','result.get("game_data_command")','result.get("instance_command")'):
   self.assertIn(token,source)
if __name__=="__main__":unittest.main()
