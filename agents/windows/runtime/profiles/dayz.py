"""DayZ runtime profile for native Windows Agents."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile,ProfileError,require_absolute,require_port,require_text,require_within
_MISSION=re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_PRIVATE_FLAGS=("-config=","-profiles=","-mission=","-storage=","-port=")
class DayZRuntimeProfile(GameRuntimeProfile):
 game_ids=("dayz","dayz.stable")
 profile_version=3
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
  instance_id=require_text(instance.get("instance_id") or instance.get("id"),"instance_id");agent_id=require_text(instance.get("agent_id"),"agent_id")
  install_path=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path")
  working=require_within(install_path,context.get("working_directory") or install_path,"working_directory")
  executable=require_within(install_path,context.get("executable") or str(Path(install_path)/"DayZServer_x64.exe"),"executable")
  config_source=require_within(working,context.get("config_path") or str(Path(working)/"serverDZ.cfg"),"config_path")
  state_root=require_absolute(context.get("instance_state_root"),"instance_state_root")
  mission=str(context.get("dayz_mission") or context.get("mission") or "dayzOffline.chernarusplus").strip()
  if not _MISSION.fullmatch(mission):raise ProfileError("invalid DayZ mission")
  mission_source=require_within(working,str(Path(working)/"mpmissions"/mission),"mission_source")
  private_config=str(Path(state_root)/"config"/"serverDZ.cfg");private_profiles=str(Path(state_root)/"profiles");private_storage=str(Path(state_root)/"storage");private_missions=str(Path(state_root)/"mpmissions");private_mission=str(Path(private_missions)/mission)
  game_port=require_port(context,"game",protocol="udp");game_aux_port=require_port(context,"game_aux",protocol="udp");steam_query_port=require_port(context,"steam_query",protocol="udp")
  extra=context.get("arguments",[])
  if not isinstance(extra,list):raise ProfileError("invalid DayZ arguments")
  arguments=[f"-config={private_config}",f"-port={game_port}",f"-profiles={private_profiles}",f"-storage={private_storage}",f"-mission={private_mission}"]
  for value in extra:
   text=str(value);lower=text.lower()
   if not text.startswith("-") or any(c in text for c in ("\x00","\n","\r")):raise ProfileError("invalid DayZ runtime argument")
   if any(lower.startswith(flag) for flag in _PRIVATE_FLAGS):raise ProfileError("DayZ private runtime path cannot be overridden")
   arguments.append(text)
  env=context.get("environment") or {}
  if not isinstance(env,dict):raise ProfileError("invalid DayZ environment")
  environment={**env,"CAPIVARA_INSTANCE_ID":instance_id,"CAPIVARA_GAME_ID":"dayz","CAPIVARA_GAME_PORT":str(game_port),"CAPIVARA_STEAM_QUERY_PORT":str(steam_query_port),"CAPIVARA_INSTANCE_STATE_ROOT":state_root}
  return {"instance_id":instance_id,"agent_id":agent_id,"game_id":"dayz","environment_id":str(instance.get("environment_id") or "dayz.stable"),"runtime_id":str(instance.get("runtime_id") or instance_id),"adapter":"windows-process","working_directory":working,"executable":executable,"arguments":arguments,"environment":environment,"desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"dayz","profile_version":self.profile_version,"ports":{"game":{"port":game_port,"protocol":"udp"},"game_aux":{"port":game_aux_port,"protocol":"udp"},"steam_query":{"port":steam_query_port,"protocol":"udp"}},"instance_state_root":state_root,"config_path":private_config,"mission":mission,"writable_directories":[str(Path(state_root)/"config"),private_profiles,private_storage,private_missions],"seed_files":[{"source":config_source,"target":private_config}],"seed_directories":[{"source":mission_source,"target":private_mission}]}
__all__=["DayZRuntimeProfile"]
