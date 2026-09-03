#!/usr/bin/env python3
"""The Isle Evrima Linux runtime profile using systemd credentials for EOS secrets."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile, require_absolute, require_port, require_text, require_within

_PREPARE_HELPER = "/opt/capivara-agent/runtime/theisle_prepare.py"

class TheIsleRuntimeProfile(GameRuntimeProfile):
    game_ids = ("theisle", "theisle.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        install_path = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        executable = require_within(install_path, context.get("executable") or str(Path(install_path) / "TheIsle/Binaries/Linux/TheIsleServer-Linux-Shipping"), "executable")
        working_directory = require_within(install_path, context.get("working_directory") or install_path, "working_directory")
        game_port = require_port(context, "game", protocol="udp")
        query_port = require_port(context, "steam_query", protocol="udp")
        runtime_name = f"capivara-theisle-{instance_id}"
        runtime_root = f"/run/{runtime_name}"
        config_target = str(Path(install_path) / "TheIsle" / "Saved" / "Config" / "LinuxServer")
        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "theisle",
            "environment_id": str(instance.get("environment_id") or "theisle.stable"),
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": ["-Port=" + str(game_port), "-QueryPort=" + str(query_port), "-log"],
            "pre_start": [{"executable": "/usr/bin/python3", "arguments": [_PREPARE_HELPER, "--runtime-config-root", runtime_root]}],
            "secret_refs": [
                {"name": "EOS_CLIENT_ID", "ref": f"instance/{instance_id}/EOS_CLIENT_ID", "target": "file"},
                {"name": "EOS_CLIENT_SECRET", "ref": f"instance/{instance_id}/EOS_CLIENT_SECRET", "target": "file"}
            ],
            "runtime_directory": runtime_name,
            "bind_paths": [{"source": str(Path(runtime_root) / "TheIsle/Saved/Config/LinuxServer"), "target": config_target}],
            "environment": {"CAPIVARA_INSTANCE_ID": instance_id, "CAPIVARA_GAME_ID": "theisle"},
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "theisle",
            "profile_version": self.profile_version,
            "ports": {"game": {"port": game_port, "protocol": "udp"}, "steam_query": {"port": query_port, "protocol": "udp"}},
            "writable_directories": [],
            "seed_files": []
        }

__all__ = ["TheIsleRuntimeProfile"]
