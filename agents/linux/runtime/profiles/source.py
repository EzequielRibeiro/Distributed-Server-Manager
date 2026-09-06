#!/usr/bin/env python3
"""Instance-isolated Source Dedicated Server runtime profile."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text, require_within


_SOURCE_LAYOUTS = {
    "garrysmod": {
        "game_directory": "garrysmod",
        "private_generated": ("data", "logs"),
    },
    "left4dead2": {
        "game_directory": "left4dead2",
        "private_generated": ("logs",),
    },
}


class SourceRuntimeProfile(GameRuntimeProfile):
    """Keep SRCDS binaries/assets shared while isolating instance-owned mutable state."""

    game_ids = (
        "garrysmod", "garrysmod.stable",
        "left4dead2", "left4dead2.stable",
    )
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        game_id = require_text(instance.get("game_id"), "game_id").lower()
        environment_id = require_text(instance.get("environment_id") or f"{game_id}.stable", "environment_id")
        layout = _SOURCE_LAYOUTS.get(game_id)
        if layout is None:
            raise ProfileError("Source runtime profile is not allowlisted for this game")

        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or not policy:
            raise ProfileError("Catalog runtime policy is required for Source runtime profile")
        if str(policy.get("runtime_id") or "").strip() != environment_id:
            raise ProfileError("Catalog runtime policy does not match environment_id")

        executable_value = str(policy.get("executable") or "").strip()
        if not executable_value or Path(executable_value).is_absolute():
            raise ProfileError("Source executable must be relative to provisioned content")
        executable = require_within(install_path, str(Path(install_path) / executable_value), "executable")

        working_value = str(policy.get("working_directory") or ".").strip() or "."
        if Path(working_value).is_absolute() or ".." in Path(working_value).parts:
            raise ProfileError("Source working directory escapes provisioned content")
        working_directory = require_within(
            install_path,
            str(Path(install_path) / working_value),
            "working_directory",
        )

        raw_arguments = context.get("arguments") or []
        if not isinstance(raw_arguments, list):
            raise ProfileError("invalid Source runtime arguments")
        arguments: list[str] = []
        for value in raw_arguments:
            text = str(value)
            if "\x00" in text or "\n" in text or "\r" in text:
                raise ProfileError("invalid Source runtime argument")
            arguments.append(text)

        raw_environment = context.get("environment") or {}
        if not isinstance(raw_environment, dict):
            raise ProfileError("invalid Source runtime environment")
        environment = {str(key): str(value) for key, value in raw_environment.items()}
        environment.update({
            "CAPIVARA_INSTANCE_ID": instance_id,
            "CAPIVARA_GAME_ID": game_id,
        })

        ports = port_bindings(context)
        binding = ports.get("game_udp")
        if not binding or binding.get("protocol") != "udp":
            raise ProfileError("Source runtime requires game_udp reservation")
        arguments = ["-port", str(binding["port"]), *arguments]

        instance_state_root = require_absolute(
            context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}",
            "instance_state_root",
        )
        game_directory = str(layout["game_directory"])
        shared_game_root = Path(install_path) / game_directory
        private_game_root = Path(instance_state_root) / game_directory
        shared_cfg = shared_game_root / "cfg"
        private_cfg = private_game_root / "cfg"

        generated = tuple(str(value) for value in layout["private_generated"])
        writable_directories = [str(private_game_root / value) for value in generated]
        bind_paths = [{"source": str(private_cfg), "target": str(shared_cfg)}]
        bind_paths.extend(
            {"source": str(private_game_root / value), "target": str(shared_game_root / value)}
            for value in generated
        )

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": game_id,
            "environment_id": environment_id,
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": arguments,
            "environment": environment,
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "source",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": instance_state_root,
            "configuration_root": str(private_cfg),
            "writable_directories": writable_directories,
            "seed_files": [],
            "seed_directories": [{"source": str(shared_cfg), "target": str(private_cfg)}],
            "bind_paths": bind_paths,
        }


__all__ = ["SourceRuntimeProfile"]
