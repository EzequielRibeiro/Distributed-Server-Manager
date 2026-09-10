#!/usr/bin/env python3
"""Palworld Linux runtime profile with isolated saved state and bootstrap file preparation."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text, require_within

class PalworldRuntimeProfile(GameRuntimeProfile):
    game_ids = ("palworld", "palworld.stable")
    profile_version = 2

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id=require_text(instance.get("instance_id") or instance.get("id"),"instance_id")
        agent_id=require_text(instance.get("agent_id"),"agent_id")
        environment_id=require_text(instance.get("environment_id") or "palworld.stable","environment_id")
        install_path=require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"),"install_path")
        policy=context.get("catalog_runtime_policy")
        if not isinstance(policy,dict) or str(policy.get("runtime_id") or "").strip()!=environment_id:raise ProfileError("matching Catalog runtime policy is required for Palworld")
        executable_value=str(policy.get("executable") or "PalServer.sh").strip()
        if Path(executable_value).is_absolute():raise ProfileError("Palworld executable must be relative to provisioned content")
        executable=require_within(install_path,str(Path(install_path)/executable_value),"executable")
        ports=port_bindings(context);binding=ports.get("game") or ports.get("game_udp")
        if not binding or binding.get("protocol")!="udp":raise ProfileError("Palworld requires a UDP game reservation")
        state_root=require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}","instance_state_root")
        shared_saved=Path(install_path)/"Pal"/"Saved";private_saved=Path(state_root)/"Pal"/"Saved"
        steamclient_source=Path(install_path)/"linux64"/"steamclient.so"
        steamclient_target=Path(install_path)/"Pal"/"Binaries"/"Linux"/"steamclient.so"
        raw_args=context.get("arguments") or []
        if not isinstance(raw_args,list):raise ProfileError("invalid Palworld runtime arguments")
        arguments=[f"-port={binding['port']}",*[str(x) for x in raw_args]]
        if any("\x00" in x or "\n" in x or "\r" in x for x in arguments):raise ProfileError("invalid Palworld runtime argument")
        raw_env=context.get("environment") or {}
        if not isinstance(raw_env,dict):raise ProfileError("invalid Palworld runtime environment")
        environment={str(k):str(v) for k,v in raw_env.items()};environment.update({"CAPIVARA_INSTANCE_ID":instance_id,"CAPIVARA_GAME_ID":"palworld"})
        return {
            "instance_id":instance_id,"agent_id":agent_id,"game_id":"palworld","environment_id":environment_id,
            "runtime_id":str(instance.get("runtime_id") or instance_id),"adapter":"systemd","working_directory":install_path,
            "executable":executable,"arguments":arguments,"environment":environment,"user":str(context.get("user") or "capivara-instance"),
            "desired_state":str(instance.get("desired_state") or context.get("desired_state") or "stopped"),"profile":"palworld","profile_version":self.profile_version,
            "ports":ports,"instance_state_root":state_root,"configuration_root":str(private_saved/"Config"/"LinuxServer"),
            "writable_directories":[str(private_saved)],"seed_files":[],
            "seed_directories":[{"source":str(shared_saved),"target":str(private_saved),"optional":True}],
            "working_file_copies":[{"source":str(steamclient_source),"target":str(steamclient_target)}],
            "bind_paths":[{"source":str(private_saved),"target":str(shared_saved)}],
        }

__all__=["PalworldRuntimeProfile"]