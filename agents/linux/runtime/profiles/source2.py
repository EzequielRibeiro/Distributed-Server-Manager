#!/usr/bin/env python3
"""Counter-Strike 2 Source 2 runtime profile with private config and logs."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text, require_within

class Source2RuntimeProfile(GameRuntimeProfile):
    game_ids = ("counterstrike2", "counterstrike2.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        environment_id = require_text(instance.get("environment_id") or "counterstrike2.stable", "environment_id")
        install_path = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or str(policy.get("runtime_id") or "").strip() != environment_id:
            raise ProfileError("matching Catalog runtime policy is required for Counter-Strike 2")
        executable_value = str(policy.get("executable") or "").strip()
        if not executable_value or Path(executable_value).is_absolute():
            raise ProfileError("Counter-Strike 2 executable must be relative to provisioned content")
        executable = require_within(install_path, str(Path(install_path) / executable_value), "executable")
        working_value = str(policy.get("working_directory") or ".").strip() or "."
        if Path(working_value).is_absolute() or ".." in Path(working_value).parts:
            raise ProfileError("Counter-Strike 2 working directory escapes provisioned content")
        working_directory = require_within(install_path, str(Path(install_path) / working_value), "working_directory")
        ports = port_bindings(context)
        binding = ports.get("game") or ports.get("game_udp")
        if not binding or binding.get("protocol") != "udp":
            raise ProfileError("Counter-Strike 2 requires a UDP game reservation")
        state_root = require_absolute(context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}", "instance_state_root")
        shared_game_root = Path(install_path) / "game" / "csgo"
        private_game_root = Path(state_root) / "game" / "csgo"
        shared_cfg, private_cfg = shared_game_root / "cfg", private_game_root / "cfg"
        shared_logs, private_logs = shared_game_root / "logs", private_game_root / "logs"
        raw_arguments = context.get("arguments") or []
        if not isinstance(raw_arguments, list):
            raise ProfileError("invalid Counter-Strike 2 runtime arguments")
        arguments = [str(value) for value in raw_arguments]
        if any("\x00" in value or "\n" in value or "\r" in value for value in arguments):
            raise ProfileError("invalid Counter-Strike 2 runtime argument")
        arguments = ["-port", str(binding["port"]), *arguments]
        raw_environment = context.get("environment") or {}
        if not isinstance(raw_environment, dict):
            raise ProfileError("invalid Counter-Strike 2 runtime environment")
        environment = {str(k): str(v) for k, v in raw_environment.items()}
        environment.update({"CAPIVARA_INSTANCE_ID": instance_id, "CAPIVARA_GAME_ID": "counterstrike2"})
        return {
            "instance_id": instance_id, "agent_id": agent_id, "game_id": "counterstrike2",
            "environment_id": environment_id, "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd", "working_directory": working_directory, "executable": executable,
            "arguments": arguments, "environment": environment, "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "source2", "profile_version": self.profile_version, "ports": ports,
            "instance_state_root": state_root, "configuration_root": str(private_cfg),
            "writable_directories": [str(private_logs)], "seed_files": [],
            "seed_directories": [{"source": str(shared_cfg), "target": str(private_cfg)}],
            "bind_paths": [
                {"source": str(private_cfg), "target": str(shared_cfg)},
                {"source": str(private_logs), "target": str(shared_logs)},
            ],
        }

__all__ = ["Source2RuntimeProfile"]
