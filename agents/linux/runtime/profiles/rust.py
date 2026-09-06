#!/usr/bin/env python3
"""Rust Linux runtime profile with instance-private identity and logs."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile,ProfileError,port_bindings,require_absolute,require_text,require_within
class RustRuntimeProfile(GameRuntimeProfile):
 game_ids=("rust","rust.stable");profile_version=1
 def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
  iid=require_text(instance.get("instance_id") or instance.get("id"),"instance_id");aid=require_text(instance.get("agent_id"),"agent_id");eid=require_text(instance.get("environment_id") or "rust.stable","environment_id")
  install=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path");state=require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{iid}","instance_state_root")
  policy=context.get("catalog_runtime_policy")
  if not isinstance(policy,dict) or str(policy.get("runtime_id") or "").strip()!=eid:raise ProfileError("matching Catalog runtime policy is required for Rust")
  policy["executable"]="";policy["arguments"]=[]
  exe=require_within(install,str(Path(install)/"RustDedicated"),"executable")
  ports=port_bindings(context)
  for role,proto in (("game","udp"),("rcon","tcp"),("query","udp")):
   if role not in ports or ports[role].get("protocol")!=proto:raise ProfileError(f"Rust requires {proto.upper()} reservation: {role}")
  runtime=str(Path(state)/"runtime");logs=str(Path(state)/"logs");logfile=str(Path(logs)/"rust.log")
  args=["-batchmode","+server.identity",iid,"+server.port",str(ports["game"]["port"]),"+rcon.port",str(ports["rcon"]["port"]),"+rcon.web","1","+server.queryport",str(ports["query"]["port"]),"-logfile",logfile,*[str(x) for x in (context.get("arguments") or [])]]
  if any("\x00" in x or "\n" in x or "\r" in x for x in args):raise ProfileError("invalid Rust runtime argument")
  return {"instance_id":iid,"agent_id":aid,"game_id":"rust","environment_id":eid,"runtime_id":str(instance.get("runtime_id") or iid),"adapter":"systemd","working_directory":runtime,"executable":exe,"arguments":args,"environment":{"CAPIVARA_INSTANCE_ID":iid,"CAPIVARA_GAME_ID":"rust"},"user":str(context.get("user") or "capivara-instance"),"desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"rust","profile_version":1,"ports":ports,"instance_state_root":state,"configuration_root":str(Path(runtime)/"server"/iid/"cfg"),"writable_directories":[runtime,logs],"seed_files":[],"seed_directories":[],"bind_paths":[]}
__all__=["RustRuntimeProfile"]
