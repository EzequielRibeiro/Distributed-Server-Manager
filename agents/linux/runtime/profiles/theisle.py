#!/usr/bin/env python3
"""The Isle Evrima Linux runtime profile using systemd credentials for EOS secrets."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile, require_absolute, require_port, require_text, require_within
_PREPARE_HELPER="/opt/capivara-agent/runtime/theisle_prepare.py"
class TheIsleRuntimeProfile(GameRuntimeProfile):
 game_ids=("theisle","theisle.stable");profile_version=2
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
  instance_id=require_text(instance.get("instance_id") or instance.get("id"),"instance_id");agent_id=require_text(instance.get("agent_id"),"agent_id")
  install_path=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path");executable=require_within(install_path,context.get("executable") or str(Path(install_path)/"TheIsle/Binaries/Linux/TheIsleServer-Linux-Shipping"),"executable");working_directory=require_within(install_path,context.get("working_directory") or install_path,"working_directory")
  game_port=require_port(context,"game",protocol="udp");query_port=require_port(context,"steam_query",protocol="udp")
  state_root=require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}","instance_state_root")
  runtime_name=f"capivara-theisle-{instance_id}";runtime_root=f"/run/{runtime_name}"
  saved_root=Path(install_path)/"TheIsle/Saved";private_saved=Path(state_root)/"TheIsle/Saved"
  config_target=str(saved_root/"Config/LinuxServer");player_target=str(saved_root/"PlayerData");logs_target=str(saved_root/"Logs")
  player_private=str(private_saved/"PlayerData");logs_private=str(private_saved/"Logs")
  return {"instance_id":instance_id,"agent_id":agent_id,"game_id":"theisle","environment_id":str(instance.get("environment_id") or "theisle.stable"),"runtime_id":str(instance.get("runtime_id") or instance_id),"adapter":"systemd","working_directory":working_directory,"executable":executable,"arguments":["-Port="+str(game_port),"-QueryPort="+str(query_port),"-log"],"pre_start":[{"executable":"/usr/bin/python3","arguments":[_PREPARE_HELPER,"--runtime-config-root",runtime_root]}],"secret_refs":[{"name":"EOS_CLIENT_ID","ref":f"instance/{instance_id}/EOS_CLIENT_ID","target":"file"},{"name":"EOS_CLIENT_SECRET","ref":f"instance/{instance_id}/EOS_CLIENT_SECRET","target":"file"}],"runtime_directory":runtime_name,"runtime_bind_paths":[{"source":runtime_root,"target":config_target}],"bind_paths":[{"source":player_private,"target":player_target},{"source":logs_private,"target":logs_target}],"environment":{"CAPIVARA_INSTANCE_ID":instance_id,"CAPIVARA_GAME_ID":"theisle"},"user":str(context.get("user") or "capivara-instance"),"desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"theisle","profile_version":self.profile_version,"ports":{"game":{"port":game_port,"protocol":"udp"},"steam_query":{"port":query_port,"protocol":"udp"}},"instance_state_root":state_root,"configuration_root":str(private_saved),"writable_directories":[player_private,logs_private],"seed_files":[],"seed_directories":[]}
__all__=["TheIsleRuntimeProfile"]
