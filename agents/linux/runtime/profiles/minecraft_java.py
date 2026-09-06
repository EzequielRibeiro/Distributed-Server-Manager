#!/usr/bin/env python3
"""Minecraft Java runtime profile with instance-private working trees.

The provider-managed installation is treated as an immutable seed. Each instance
receives its own working tree under the selected Storage Pool so worlds, configs,
logs, plugins and mods can never collide across instances.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text


_JAVA_ENVIRONMENTS = (
    "minecraft.java.arclight",
    "minecraft.java.fabric",
    "minecraft.java.folia",
    "minecraft.java.forge",
    "minecraft.java.neoforge",
    "minecraft.java.paper",
    "minecraft.java.purpur",
    "minecraft.java.quilt",
    "minecraft.java.spongevanilla",
    "minecraft.java.vanilla",
    "minecraft.java.youer",
)


class MinecraftJavaRuntimeProfile(GameRuntimeProfile):
    game_ids = _JAVA_ENVIRONMENTS
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        environment_id = require_text(instance.get("environment_id"), "environment_id").lower()
        if environment_id not in _JAVA_ENVIRONMENTS:
            raise ProfileError("unsupported Minecraft Java environment")

        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or str(policy.get("runtime_id") or "").strip().lower() != environment_id:
            raise ProfileError("matching Catalog runtime policy is required for Minecraft Java")
        if str(policy.get("engine") or "java").strip().lower() not in {"", "java"}:
            raise ProfileError("Minecraft Java runtime policy must use the Java engine")

        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        state_root = require_absolute(context.get("instance_state_root"), "instance_state_root")
        runtime_root = str(Path(state_root) / "runtime")
        ports = port_bindings(context)
        if not ports:
            raise ProfileError("Minecraft Java runtime requires reserved ports")

        environment = context.get("environment") or {}
        if not isinstance(environment, dict):
            raise ProfileError("invalid Minecraft Java environment")

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "minecraft",
            "environment_id": environment_id,
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": runtime_root,
            "executable": "/usr/bin/java",
            "arguments": [],
            "environment": {
                **{str(k): str(v) for k, v in environment.items()},
                "CAPIVARA_INSTANCE_ID": instance_id,
                "CAPIVARA_GAME_ID": "minecraft",
                "CAPIVARA_ENVIRONMENT_ID": environment_id,
                "CAPIVARA_INSTANCE_STATE_ROOT": state_root,
            },
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "minecraft-java",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": state_root,
            "configuration_root": runtime_root,
            "writable_directories": [runtime_root],
            "seed_files": [],
            "seed_directories": [{"source": install_path, "target": runtime_root}],
            "bind_paths": [],
        }


__all__ = ["MinecraftJavaRuntimeProfile"]
