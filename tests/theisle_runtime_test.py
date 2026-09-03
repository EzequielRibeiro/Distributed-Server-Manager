#!/usr/bin/env python3
import os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"agents/linux/runtime"));sys.path.insert(0,str(ROOT/"agents/linux/runtime/materializers"))
from profiles.theisle import TheIsleRuntimeProfile
from runtime_spec import validate_runtime_spec
from runtime_secret_store import put_secret
from materializers.systemd import render_unit

def main():
 with tempfile.TemporaryDirectory() as td:
  os.environ["CAPIVARA_RUNTIME_SECRET_ROOT"]=str(Path(td)/"secrets")
  install=Path(td)/"server";(install/"TheIsle/Binaries/Linux").mkdir(parents=True);(install/"TheIsle/Saved/Config/LinuxServer").mkdir(parents=True);(install/"TheIsle/Binaries/Linux/TheIsleServer-Linux-Shipping").write_text("")
  instance={"instance_id":"isle-1","agent_id":"agent-1","environment_id":"theisle.stable"};context={"install_path":str(install),"ports":[{"role":"game","port":7777,"protocol":"udp"},{"role":"steam_query","port":27015,"protocol":"udp"}]}
  spec=validate_runtime_spec(TheIsleRuntimeProfile().build_runtime_spec(instance,context),expected_agent_id="agent-1")
  assert [x["name"] for x in spec["secret_refs"]]==["EOS_CLIENT_ID","EOS_CLIENT_SECRET"]
  put_secret("instance/isle-1/EOS_CLIENT_ID","client-id",expected_instance_id="isle-1");put_secret("instance/isle-1/EOS_CLIENT_SECRET","super-secret",expected_instance_id="isle-1")
  unit=render_unit(spec);assert "LoadCredential=EOS_CLIENT_ID:" in unit and "LoadCredential=EOS_CLIENT_SECRET:" in unit;assert "super-secret" not in unit and "client-id" not in unit;assert "ClientSecret" not in " ".join(spec["arguments"]);assert "RuntimeDirectory=capivara-theisle-isle-1" in unit
 print("theisle_runtime_test: ok")
if __name__=="__main__":main()
