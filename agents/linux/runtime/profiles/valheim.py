#!/usr/bin/env python3
"""Valheim Linux runtime profile with private saves and credential-backed password injection."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile,ProfileError,port_bindings,require_absolute,require_text,require_within

_LAUNCHER="/opt/capivara-agent/runtime/valheim_launch.py"

class ValheimRuntimeProfile(GameRuntimeProfile):
 game_ids=("valheim","valheim.stable");profile_version=1
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
  iid=require_text(instance.get("instance_id") or instance.get("id"),"instance_id");aid=require_text(instance.get("agent_id"),"agent_id");eid=require_text(instance.get("environment_id") or "valheim.stable","environment_id")
  install=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path");state=require_absolute(context.get("instance_state_root"),"instance_state_root")
  policy=context.get("catalog_runtime_policy")
  if not isinstance(policy,dict) or str(policy.get("runtime_id") or "").strip()!=eid:raise ProfileError("matching Catalog runtime policy is required for Valheim")
  server=require_within(install,str(Path(install)/"valheim_server.x86_64"),"executable")
  ports=port_bindings(context);game=ports.get("game");aux=ports.get("game_aux")
  if not game or game.get("protocol")!="udp":raise ProfileError("Valheim requires UDP game reservation")
  if not aux or aux.get("protocol")!="udp":raise ProfileError("Valheim requires UDP game_aux reservation")
  if int(aux["port"])!=int(game["port"])+1:raise ProfileError("Valheim game_aux must be game port + 1")
  save_root=str(Path(state)/"valheim")
  raw_extra=context.get("arguments") or []
  if not isinstance(raw_extra,list):raise ProfileError("invalid Valheim runtime arguments")
  extra=[str(x) for x in raw_extra]
  if any("\x00" in x or "\n" in x or "\r" in x for x in extra):raise ProfileError("invalid Valheim runtime argument")
  forbidden={"-password","-port","-savedir"}
  if any(x.lower() in forbidden for x in extra):raise ProfileError("Valheim runtime owns password, port and savedir arguments")
  name=str(context.get("server_name") or "Capivara Valheim").strip() or "Capivara Valheim";world=str(context.get("world_name") or "Dedicated").strip() or "Dedicated"
  if any(c in name+world for c in ("\x00","\n","\r")):raise ProfileError("invalid Valheim server metadata")
  policy["executable"]="";policy["arguments"]=[]
  game_args=["-name",name,"-port",str(game["port"]),"-world",world,"-savedir",save_root,"-public","1",*extra]
  return {"instance_id":iid,"agent_id":aid,"game_id":"valheim","environment_id":eid,"runtime_id":str(instance.get("runtime_id") or iid),"adapter":"systemd","working_directory":install,"executable":"/usr/bin/python3","arguments":[_LAUNCHER,"--server",server,"--password-credential","VALHEIM_PASSWORD","--",*game_args],"secret_refs":[{"name":"VALHEIM_PASSWORD","ref":f"instance/{iid}/VALHEIM_PASSWORD","target":"file"}],"environment":{"CAPIVARA_INSTANCE_ID":iid,"CAPIVARA_GAME_ID":"valheim"},"user":str(context.get("user") or "capivara-instance"),"desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"valheim","profile_version":self.profile_version,"ports":ports,"instance_state_root":state,"configuration_root":save_root,"writable_directories":[save_root],"seed_files":[],"seed_directories":[]}

__all__=["ValheimRuntimeProfile"]
