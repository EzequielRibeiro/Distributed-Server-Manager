#!/usr/bin/env python3
"""Project Zomboid runtime profile with private per-instance state and safe first-start bootstrap."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, require_absolute, require_port, require_text, require_within

_BOOTSTRAP_HELPER = "/opt/capivara-agent/runtime/projectzomboid_bootstrap.py"


class ProjectZomboidRuntimeProfile(GameRuntimeProfile):
    game_ids = ("projectzomboid", "projectzomboid.stable")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        working_directory = require_within(
            install_path,
            context.get("working_directory") or install_path,
            "working_directory",
        )
        executable = require_within(
            install_path,
            context.get("executable") or str(Path(install_path) / "start-server.sh"),
            "executable",
        )
        instance_state_root = require_absolute(
            context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}",
            "instance_state_root",
        )
        game_port = require_port(context, "game", protocol="udp")

        extra_arguments = context.get("arguments", [])
        if not isinstance(extra_arguments, list):
            raise ProfileError("invalid Project Zomboid arguments")
        arguments = ["-servername", "servertest", "-port", str(game_port)]
        for value in extra_arguments:
            text = str(value)
            if "\x00" in text or "\n" in text or "\r" in text:
                raise ProfileError("invalid Project Zomboid runtime argument")
            arguments.append(text)

        raw_environment = context.get("environment") or {}
        if not isinstance(raw_environment, dict):
            raise ProfileError("invalid Project Zomboid environment")
        environment = dict(raw_environment)
        environment.update({
            "CAPIVARA_INSTANCE_ID": instance_id,
            "CAPIVARA_GAME_ID": "projectzomboid",
            "CAPIVARA_GAME_PORT": str(game_port),
        })

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "projectzomboid",
            "environment_id": str(instance.get("environment_id") or "projectzomboid.stable"),
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": arguments,
            "pre_start": [{
                "executable": "/usr/bin/python3",
                "arguments": [_BOOTSTRAP_HELPER, "--servername", "servertest", "--port", str(game_port)],
            }],
            "environment": environment,
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "projectzomboid",
            "profile_version": self.profile_version,
            "ports": {"game": {"port": game_port, "protocol": "udp"}},
            "instance_state_root": instance_state_root,
            "configuration_root": str(Path(instance_state_root) / "Zomboid" / "Server"),
            "writable_directories": [
                str(Path(instance_state_root) / "Zomboid"),
                str(Path(instance_state_root) / ".capivara"),
            ],
            "seed_files": [],
            "bind_paths": [],
        }


__all__ = ["ProjectZomboidRuntimeProfile"]
