#!/usr/bin/env python3
"""Arma Reforger Linux runtime profile with private generated server config."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, require_absolute, require_port, require_text, require_within

_PREPARE_HELPER = "/opt/capivara-agent/runtime/armareforger_prepare.py"


class ArmaReforgerRuntimeProfile(GameRuntimeProfile):
    game_ids = ("armareforger", "armareforger.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        install_path = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        working_directory = require_within(install_path, context.get("working_directory") or install_path, "working_directory")
        executable = require_within(install_path, context.get("executable") or str(Path(install_path) / "ArmaReforgerServer"), "executable")
        state_root = require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}", "instance_state_root")
        config_path = str(Path(state_root) / "config" / "server.json")
        profile_path = str(Path(state_root) / "profile")
        game_port = require_port(context, "game", protocol="udp")
        query_port = require_port(context, "steam_query", protocol="udp")
        name = f"Capivara-{instance_id}"[:128]
        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "armareforger",
            "environment_id": str(instance.get("environment_id") or "armareforger.stable"),
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": ["-config", config_path, "-profile", profile_path, "-bindPort", str(game_port), "-a2sPort", str(query_port), "-maxFPS", "60"],
            "pre_start": [{
                "executable": "/usr/bin/python3",
                "arguments": [_PREPARE_HELPER, "--config", config_path, "--game-port", str(game_port), "--query-port", str(query_port), "--name", name],
            }],
            "environment": {"CAPIVARA_INSTANCE_ID": instance_id, "CAPIVARA_GAME_ID": "armareforger", "CAPIVARA_GAME_PORT": str(game_port), "CAPIVARA_STEAM_QUERY_PORT": str(query_port)},
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "armareforger",
            "profile_version": self.profile_version,
            "ports": {"game": {"port": game_port, "protocol": "udp"}, "steam_query": {"port": query_port, "protocol": "udp"}},
            "instance_state_root": state_root,
            "configuration_root": str(Path(state_root) / "config"),
            "config_path": config_path,
            "writable_directories": [str(Path(state_root) / "config"), profile_path, str(Path(state_root) / "logs")],
            "seed_files": [],
            "bind_paths": [],
        }


__all__ = ["ArmaReforgerRuntimeProfile"]
