"""Palworld Windows runtime profile with instance-private server tree."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile,ProfileError,port_bindings,require_absolute,require_text

class PalworldRuntimeProfile(GameRuntimeProfile):
    game_ids=("palworld","palworld.stable","palworld.windows-modded")
    profile_version=1

    def build_runtime_spec(self,instance:dict[str,Any],context:dict[str,Any])->dict[str,Any]:
        iid=require_text(instance.get("instance_id") or instance.get("id"),"instance_id")
        aid=require_text(instance.get("agent_id"),"agent_id")
        eid=require_text(instance.get("environment_id") or "palworld.stable","environment_id")
        install=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path")
        state=require_absolute(context.get("instance_state_root"),"instance_state_root")
        policy=context.get("catalog_runtime_policy")
        if not isinstance(policy,dict) or str(policy.get("runtime_id") or "").strip()!=eid:
            raise ProfileError("matching Catalog runtime policy is required for Palworld")
        ports=port_bindings(context)
        for role,proto in (("game","udp"),("rcon","tcp"),("rest_api","tcp")):
            if role not in ports or ports[role].get("protocol")!=proto:
                raise ProfileError(f"Palworld requires {proto.upper()} reservation: {role}")
        runtime=str(Path(state)/"runtime")
        exe=str(Path(runtime)/"PalServer.exe")
        policy["executable"]=exe
        policy["arguments"]=[]
        extra=context.get("arguments") or []
        if not isinstance(extra,list):raise ProfileError("invalid Palworld runtime arguments")
        args=[f"-port={ports['game']['port']}",*[str(x) for x in extra]]
        if any("\x00" in x or "\n" in x or "\r" in x for x in args):
            raise ProfileError("invalid Palworld runtime argument")
        return {
            "instance_id":iid,"agent_id":aid,"game_id":"palworld","environment_id":eid,
            "runtime_id":str(instance.get("runtime_id") or iid),"adapter":"windows-process",
            "working_directory":runtime,"executable":exe,"executable_scope":"working-directory",
            "arguments":args,
            "environment":{"CAPIVARA_INSTANCE_ID":iid,"CAPIVARA_GAME_ID":"palworld"},
            "desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile":"palworld","profile_version":self.profile_version,"ports":ports,
            "instance_state_root":state,
            "configuration_root":str(Path(runtime)/"Pal"/"Saved"/"Config"/"WindowsServer"),
            "writable_directories":[],
            "seed_source_root":install,
            "seed_files":[],
            "seed_directories":[{"source":install,"target":runtime}],
        }

__all__=["PalworldRuntimeProfile"]
