#!/usr/bin/env python3
import os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"agents/linux/runtime"));sys.path.insert(0,str(ROOT/"agents/linux/runtime/materializers"))
from profiles.theisle import TheIsleRuntimeProfile
from runtime_spec import RuntimeSpecError,validate_runtime_spec
from runtime_secret_store import put_secret
from materializers.systemd import render_unit

def build(install:Path,instance_id:str):
 instance={"instance_id":instance_id,"agent_id":"agent-1","game_id":"theisle","environment_id":"theisle.stable"}
 context={"install_path":str(install),"instance_state_root":f"/var/lib/capivara-instances/{instance_id}","ports":[{"role":"game","port":7777,"protocol":"udp"},{"role":"steam_query","port":27015,"protocol":"udp"}]}
 return validate_runtime_spec(TheIsleRuntimeProfile().build_runtime_spec(instance,context),expected_agent_id="agent-1")

def main():
 with tempfile.TemporaryDirectory() as td:
  os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"]=str(Path(td)/"secrets")
  install=Path(td)/"server";(install/"TheIsle/Binaries/Linux").mkdir(parents=True);(install/"TheIsle/Saved/Config/LinuxServer").mkdir(parents=True);(install/"TheIsle/Binaries/Linux/TheIsleServer-Linux-Shipping").write_text("")
  spec=build(install,"isle-1")
  assert spec["profile_version"]==2
  assert [x["name"] for x in spec["secret_refs"]]==["EOS_CLIENT_ID","EOS_CLIENT_SECRET"]
  assert spec["runtime_bind_paths"]==[{"source":"/run/capivara-theisle-isle-1","target":str(install/"TheIsle/Saved/Config/LinuxServer")}]
  private=Path("/var/lib/capivara-instances/isle-1/TheIsle/Saved")
  assert spec["bind_paths"]==[
   {"source":str(private/"PlayerData"),"target":str(install/"TheIsle/Saved/PlayerData")},
   {"source":str(private/"Logs"),"target":str(install/"TheIsle/Saved/Logs")},
  ]
  assert set(spec["writable_directories"])=={str(private/"PlayerData"),str(private/"Logs")}
  put_secret("instance/isle-1/EOS_CLIENT_ID","client-id",expected_instance_id="isle-1");put_secret("instance/isle-1/EOS_CLIENT_SECRET","super-secret",expected_instance_id="isle-1")
  unit=render_unit(spec);assert "LoadCredential=EOS_CLIENT_ID:" in unit and "LoadCredential=EOS_CLIENT_SECRET:" in unit;assert "super-secret" not in unit and "client-id" not in unit;assert "ClientSecret" not in " ".join(spec["arguments"]);assert "RuntimeDirectory=capivara-theisle-isle-1" in unit
  assert f"BindPaths=/run/capivara-theisle-isle-1:{install}/TheIsle/Saved/Config/LinuxServer" in unit
  assert f"BindPaths={private}/PlayerData:{install}/TheIsle/Saved/PlayerData" in unit
  assert f"BindPaths={private}/Logs:{install}/TheIsle/Saved/Logs" in unit
  second=build(install,"isle-2")
  assert {x["source"] for x in spec["bind_paths"]}.isdisjoint({x["source"] for x in second["bind_paths"]})
  assert {x["target"] for x in spec["bind_paths"]}=={x["target"] for x in second["bind_paths"]}
  bad=dict(spec);bad["runtime_bind_paths"]=[{"source":"/run/another-service","target":str(install/"TheIsle/Saved/Config/LinuxServer")}]
  try:validate_runtime_spec(bad,expected_agent_id="agent-1")
  except RuntimeSpecError:pass
  else:raise AssertionError("runtime bind outside declared RuntimeDirectory was accepted")
 print("theisle_runtime_test: ok")
if __name__=="__main__":main()
