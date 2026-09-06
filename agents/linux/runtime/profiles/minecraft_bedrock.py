#!/usr/bin/env python3
"""Minecraft Bedrock runtime profile with an instance-private working tree."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text

_BEDROCK_ENVIRONMENT = "minecraft.bedrock.vanilla"


class MinecraftBedrockRuntimeProfile(GameRuntimeProfile):
    game_ids = (_BEDROCK_ENVIRONMENT,)
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        environment_id = require_text(instance.get("environment_id"), "environment_id").lower()
        if environment_id != _BEDROCK_ENVIRONMENT:
            raise ProfileError("unsupported Minecraft Bedrock environment")

        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or str(policy.get("runtime_id") or "").strip().lower() != environment_id:
            raise ProfileError("matching Catalog runtime policy is required for Minecraft Bedrock")
        if str(policy.get("engine") or "native").strip().lower() not in {"", "native"}:
            raise ProfileError("Minecraft Bedrock runtime policy must use the native engine")

        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        state_root = require_absolute(context.get("instance_state_root"), "instance_state_root")
        runtime_root = str(Path(state_root) / "runtime")
        ports = port_bindings(context)
        for role in ("game_ipv4", "game_ipv6"):
            binding = ports.get(role)
            if not isinstance(binding, dict) or str(binding.get("protocol") or "").lower() != "udp" or not binding.get("port"):
                raise ProfileError(f"required reserved UDP port is missing: {role}")

        environment = context.get("environment") or {}
        if not isinstance(environment, dict):
            raise ProfileError("invalid Minecraft Bedrock environment")

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "minecraft",
            "environment_id": environment_id,
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": runtime_root,
            # Catalog policy resolves the provider-managed executable from install_path.
            # All relative reads/writes remain inside the private seeded working tree.
            "executable": str(Path(install_path) / "bedrock_server"),
            "arguments": [],
            "environment": {
                **{str(k): str(v) for k, v in environment.items()},
                "LD_LIBRARY_PATH": runtime_root,
                "CAPIVARA_INSTANCE_ID": instance_id,
                "CAPIVARA_GAME_ID": "minecraft",
                "CAPIVARA_ENVIRONMENT_ID": environment_id,
                "CAPIVARA_INSTANCE_STATE_ROOT": state_root,
            },
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "minecraft-bedrock",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": state_root,
            "configuration_root": runtime_root,
            "writable_directories": [runtime_root],
            "seed_files": [],
            "seed_directories": [{"source": install_path, "target": runtime_root}],
            "bind_paths": [],
        }


__all__ = ["MinecraftBedrockRuntimeProfile"]
