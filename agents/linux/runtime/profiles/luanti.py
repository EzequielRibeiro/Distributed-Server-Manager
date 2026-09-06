#!/usr/bin/env python3
"""Luanti dedicated-server runtime profile with instance-private world state."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, require_absolute, require_port, require_text, require_within


class LuantiRuntimeProfile(GameRuntimeProfile):
    game_ids = ("luanti", "luanti.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        environment_id = require_text(instance.get("environment_id") or "luanti.stable", "environment_id")
        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or str(policy.get("runtime_id") or "").strip() != environment_id:
            raise ProfileError("matching Catalog runtime policy is required for Luanti")

        executable_value = str(policy.get("executable") or "").strip()
        if not executable_value or Path(executable_value).is_absolute():
            raise ProfileError("Luanti executable must be relative to provisioned content")
        executable = require_within(
            install_path,
            str(Path(install_path) / executable_value),
            "executable",
        )
        working_directory = require_within(
            install_path,
            str(Path(executable).parent.parent),
            "working_directory",
        )
        state_root = require_absolute(
            context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}",
            "instance_state_root",
        )
        world_path = str(Path(state_root) / "world")
        game_port = require_port(context, "game", protocol="udp")

        raw_extra = context.get("arguments") or []
        if not isinstance(raw_extra, list):
            raise ProfileError("invalid Luanti runtime arguments")
        extra = [str(value) for value in raw_extra]
        if any("\x00" in value or "\n" in value or "\r" in value for value in extra):
            raise ProfileError("invalid Luanti runtime argument")
        owned = {"--world", "--worldname", "--port", "--config"}
        if any(value.lower() in owned for value in extra):
            raise ProfileError("Luanti runtime owns world, port and configuration paths")

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "luanti",
            "environment_id": environment_id,
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": ["--world", world_path, "--port", str(game_port), *extra],
            "environment": {
                "CAPIVARA_INSTANCE_ID": instance_id,
                "CAPIVARA_GAME_ID": "luanti",
                "CAPIVARA_GAME_PORT": str(game_port),
            },
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "luanti",
            "profile_version": self.profile_version,
            "ports": {"game": {"port": game_port, "protocol": "udp"}},
            "instance_state_root": state_root,
            "configuration_root": str(Path(state_root) / "config"),
            "writable_directories": [
                str(Path(state_root) / "world"),
                str(Path(state_root) / "config"),
                str(Path(state_root) / "logs"),
            ],
            "seed_files": [],
            "bind_paths": [],
        }


__all__ = ["LuantiRuntimeProfile"]
