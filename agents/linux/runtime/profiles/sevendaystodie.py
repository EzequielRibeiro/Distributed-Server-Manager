#!/usr/bin/env python3
"""7 Days to Die Linux runtime profile with private XML config and logs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_port, require_text, require_within

_PREPARE_HELPER = "/opt/capivara-agent/runtime/sevendaystodie_prepare.py"


class SevenDaysToDieRuntimeProfile(GameRuntimeProfile):
    game_ids = ("sevendaystodie", "sevendaystodie.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        install_path = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        working_directory = require_within(install_path, context.get("working_directory") or install_path, "working_directory")
        executable = require_within(install_path, context.get("executable") or str(Path(install_path) / "7DaysToDieServer.x86_64"), "executable")
        state_root = require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}", "instance_state_root")
        config_path = str(Path(state_root) / "config" / "serverconfig.xml")
        log_path = str(Path(state_root) / "logs" / "output_log.txt")
        game_port = require_port(context, "game", protocol="udp")
        ports = port_bindings(context)
        for role in ("game_tcp", "game_aux_1", "game_aux_2", "game_aux_3"):
            if role not in ports:
                raise ProfileError(f"required reserved port is missing: {role}")

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "sevendaystodie",
            "environment_id": str(instance.get("environment_id") or "sevendaystodie.stable"),
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": ["-logfile", log_path, "-quit", "-batchmode", "-nographics", f"-configfile={config_path}", "-dedicated"],
            "pre_start": [{"executable": "/usr/bin/python3", "arguments": [_PREPARE_HELPER, "--config", config_path, "--port", str(game_port)]}],
            "environment": {"CAPIVARA_INSTANCE_ID": instance_id, "CAPIVARA_GAME_ID": "sevendaystodie", "CAPIVARA_GAME_PORT": str(game_port)},
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "sevendaystodie",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": state_root,
            "configuration_root": str(Path(state_root) / "config"),
            "config_path": config_path,
            "seed_files": [{"source": str(Path(install_path) / "serverconfig.xml"), "target": config_path}],
            "writable_directories": [str(Path(state_root) / "config"), str(Path(state_root) / "logs")],
            "bind_paths": [],
        }


__all__ = ["SevenDaysToDieRuntimeProfile"]
