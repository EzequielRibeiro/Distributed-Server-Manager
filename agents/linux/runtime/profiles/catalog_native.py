#!/usr/bin/env python3
"""Generic allowlisted native Linux runtime profile driven by CatalogRuntimePolicy.

This profile is intentionally opt-in. It is used only for dedicated servers whose
runtime contract is fully expressible as a native executable plus validated argv,
environment and reserved ports. Games needing private config bootstrapping or other
special lifecycle behavior keep dedicated profiles instead of weakening this one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text, require_within


class CatalogNativeRuntimeProfile(GameRuntimeProfile):
    game_ids = (
        "satisfactory", "satisfactory.stable",
        "garrysmod", "garrysmod.stable",
        "left4dead2", "left4dead2.stable",
    )
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        game_id = require_text(instance.get("game_id"), "game_id").lower()
        environment_id = require_text(instance.get("environment_id") or f"{game_id}.stable", "environment_id")
        if game_id not in {"satisfactory", "garrysmod", "left4dead2"}:
            raise ProfileError("generic native profile is not allowlisted for this game")

        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or not policy:
            raise ProfileError("Catalog runtime policy is required for generic native profile")
        if str(policy.get("runtime_id") or "").strip() != environment_id:
            raise ProfileError("Catalog runtime policy does not match environment_id")

        executable_value = str(policy.get("executable") or "").strip()
        if not executable_value or Path(executable_value).is_absolute():
            raise ProfileError("generic native executable must be relative to provisioned content")
        executable = require_within(install_path, str(Path(install_path) / executable_value), "executable")

        working_value = str(policy.get("working_directory") or ".").strip() or "."
        if Path(working_value).is_absolute() or ".." in Path(working_value).parts:
            raise ProfileError("generic native working directory escapes provisioned content")
        working_directory = require_within(install_path, str(Path(install_path) / working_value), "working_directory")

        raw_arguments = context.get("arguments") or []
        if not isinstance(raw_arguments, list):
            raise ProfileError("invalid generic native runtime arguments")
        arguments: list[str] = []
        for value in raw_arguments:
            text = str(value)
            if "\x00" in text or "\n" in text or "\r" in text:
                raise ProfileError("invalid generic native runtime argument")
            arguments.append(text)

        raw_environment = context.get("environment") or {}
        if not isinstance(raw_environment, dict):
            raise ProfileError("invalid generic native runtime environment")
        environment = {str(key): str(value) for key, value in raw_environment.items()}
        environment.update({
            "CAPIVARA_INSTANCE_ID": instance_id,
            "CAPIVARA_GAME_ID": game_id,
        })

        instance_state_root = require_absolute(
            context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}",
            "instance_state_root",
        )
        ports = port_bindings(context)
        if not ports:
            raise ProfileError("generic native runtime requires reserved ports")

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
            "profile": "catalog-native",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": instance_state_root,
            "configuration_root": str(Path(instance_state_root) / "config"),
            "writable_directories": [
                str(Path(instance_state_root) / "config"),
                str(Path(instance_state_root) / "data"),
                str(Path(instance_state_root) / "logs"),
            ],
            "seed_files": [],
            "bind_paths": [],
        }


__all__ = ["CatalogNativeRuntimeProfile"]
