#!/usr/bin/env python3
"""Factorio headless runtime profile with private save, settings and logs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, require_absolute, require_port, require_text, require_within

_PREPARE_HELPER = "/opt/capivara-agent/runtime/factorio_prepare.py"


class FactorioRuntimeProfile(GameRuntimeProfile):
    game_ids = ("factorio", "factorio.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        install_path = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        executable = require_within(install_path, context.get("executable") or str(Path(install_path) / "factorio" / "bin" / "x64" / "factorio"), "executable")
        working_directory = require_within(install_path, context.get("working_directory") or str(Path(executable).parent), "working_directory")
        state_root = require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}", "instance_state_root")
        save_path = str(Path(state_root) / "saves" / "capivara.zip")
        settings_path = str(Path(state_root) / "config" / "server-settings.json")
        log_path = str(Path(state_root) / "logs" / "server.log")
        game_port = require_port(context, "game", protocol="udp")
        server_name = f"Capivara-{instance_id}"[:128]
        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "factorio",
            "environment_id": str(instance.get("environment_id") or "factorio.stable"),
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": ["--start-server", save_path, "--server-settings", settings_path, "--console-log", log_path],
            "pre_start": [{
                "executable": "/usr/bin/python3",
                "arguments": [_PREPARE_HELPER, "--executable", executable, "--save", save_path, "--settings", settings_path, "--name", server_name],
            }],
            "environment": {"CAPIVARA_INSTANCE_ID": instance_id, "CAPIVARA_GAME_ID": "factorio", "CAPIVARA_GAME_PORT": str(game_port)},
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "factorio",
            "profile_version": self.profile_version,
            "ports": {"game": {"port": game_port, "protocol": "udp"}},
            "instance_state_root": state_root,
            "configuration_root": str(Path(state_root) / "config"),
            "writable_directories": [str(Path(state_root) / "config"), str(Path(state_root) / "saves"), str(Path(state_root) / "logs")],
            "seed_files": [],
            "bind_paths": [],
        }


__all__ = ["FactorioRuntimeProfile"]
