#!/usr/bin/env python3
"""DayZ runtime profile.

The profile consumes already-provisioned content and reserved ports while keeping
mutable instance configuration and persistence outside the shared Steam content.
It never allocates ports and never executes shell commands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, require_absolute, require_port, require_text, require_within

_MISSION = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class DayZRuntimeProfile(GameRuntimeProfile):
    game_ids = ("dayz", "dayz.stable")

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        install_path = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        working_directory = require_within(install_path, context.get("working_directory") or install_path, "working_directory")
        executable = require_within(install_path, context.get("executable") or str(Path(install_path) / "DayZServer"), "executable")

        instance_state_root = require_absolute(
            context.get("instance_state_root") or f"/var/lib/capivara-instances/{instance_id}",
            "instance_state_root",
        )
        default_config = str(Path(instance_state_root) / "config" / "serverDZ.cfg")
        config_path = require_within(instance_state_root, context.get("config_path") or default_config, "config_path")
        configuration_root = str(Path(config_path).parent)
        profile_path = str(Path(instance_state_root) / "profiles")
        persistence_path = str(Path(instance_state_root) / "storage_1")

        mission = str(context.get("mission") or context.get("dayz_mission") or "dayzOffline.chernarusplus").strip()
        if not _MISSION.fullmatch(mission):
            raise ProfileError("invalid DayZ mission")
        persistence_target = str(Path(install_path) / "mpmissions" / mission / "storage_1")

        game_port = require_port(context, "game", protocol="udp")
        game_aux_port = require_port(context, "game_aux", protocol="udp")
        steam_query_port = require_port(context, "steam_query", protocol="udp")

        extra_arguments = context.get("arguments", [])
        if not isinstance(extra_arguments, list):
            raise ProfileError("invalid DayZ arguments")
        arguments = [f"-config={config_path}", f"-port={game_port}", f"-profiles={profile_path}"]
        for value in extra_arguments:
            text = str(value)
            if not text.startswith("-") or "\x00" in text or "\n" in text or "\r" in text:
                raise ProfileError("invalid DayZ runtime argument")
            arguments.append(text)

        raw_environment = context.get("environment") or {}
        if not isinstance(raw_environment, dict):
            raise ProfileError("invalid DayZ environment")
        environment = dict(raw_environment)
        environment.update({
            "CAPIVARA_INSTANCE_ID": instance_id,
            "CAPIVARA_GAME_ID": "dayz",
            "CAPIVARA_GAME_PORT": str(game_port),
            "CAPIVARA_STEAM_QUERY_PORT": str(steam_query_port),
        })
        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "dayz",
            "environment_id": str(instance.get("environment_id") or "dayz.stable"),
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "systemd",
            "working_directory": working_directory,
            "executable": executable,
            "arguments": arguments,
            "environment": environment,
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "dayz",
            "profile_version": 3,
            "ports": {
                "game": {"port": game_port, "protocol": "udp"},
                "game_aux": {"port": game_aux_port, "protocol": "udp"},
                "steam_query": {"port": steam_query_port, "protocol": "udp"},
            },
            "instance_state_root": instance_state_root,
            "configuration_root": configuration_root,
            "config_path": config_path,
            "seed_files": [{
                "source": str(Path(install_path) / "serverDZ.cfg"),
                "target": config_path,
            }],
            "writable_directories": [profile_path, persistence_path],
            "bind_paths": [{
                "source": persistence_path,
                "target": persistence_target,
            }],
        }


__all__ = ["DayZRuntimeProfile"]
