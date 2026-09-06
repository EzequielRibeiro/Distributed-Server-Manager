#!/usr/bin/env python3
"""Arma 3 Linux runtime profile with private profiles/log state."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile,ProfileError,port_bindings,require_absolute,require_text,require_within
class Arma3RuntimeProfile(GameRuntimeProfile):
 game_ids=("arma3","arma3.stable");profile_version=1
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
  instance_id=require_text(instance.get("instance_id") or instance.get("id"),"instance_id");agent_id=require_text(instance.get("agent_id"),"agent_id");environment_id=require_text(instance.get("environment_id") or "arma3.stable","environment_id")
  install=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path");state=require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}","instance_state_root")
  policy=context.get("catalog_runtime_policy")
  if not isinstance(policy,dict) or str(policy.get("runtime_id") or "").strip()!=environment_id:raise ProfileError("matching Catalog runtime policy is required for Arma 3")
  policy["executable"]=""
  executable=require_within(install,str(Path(install)/"arma3server_x64"),"executable")
  ports=port_bindings(context);required=("game","steam_query","steam_master","von_reserved","battleye")
  for role in required:
   if role not in ports or ports[role].get("protocol")!="udp":raise ProfileError(f"Arma 3 requires UDP reservation: {role}")
  profiles=str(Path(state)/"profiles");args=[f"-port={ports['game']['port']}",f"-profiles={profiles}","-name=server",*[str(x) for x in (context.get("arguments") or [])]]
  return {"instance_id":instance_id,"agent_id":agent_id,"game_id":"arma3","environment_id":environment_id,"runtime_id":str(instance.get("runtime_id") or instance_id),"adapter":"systemd","working_directory":install,"executable":executable,"arguments":args,"environment":{"CAPIVARA_INSTANCE_ID":instance_id,"CAPIVARA_GAME_ID":"arma3"},"user":str(context.get("user") or "capivara-instance"),"desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"arma3","profile_version":1,"ports":ports,"instance_state_root":state,"configuration_root":profiles,"writable_directories":[profiles],"seed_files":[],"seed_directories":[],"bind_paths":[]}
__all__=["Arma3RuntimeProfile"]
