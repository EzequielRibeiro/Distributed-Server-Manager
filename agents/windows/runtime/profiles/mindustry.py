"""Mindustry dedicated-server runtime profile with instance-private state on Windows."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text


class MindustryRuntimeProfile(GameRuntimeProfile):
    game_ids = ("mindustry", "mindustry.github")
    profile_version = 1

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        instance_id = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        agent_id = require_text(instance.get("agent_id"), "agent_id")
        environment_id = str(instance.get("environment_id") or "mindustry.github").strip().lower()
        if environment_id != "mindustry.github":
            raise ProfileError("unsupported Mindustry environment")
        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or str(policy.get("runtime_id") or "").strip().lower() != environment_id:
            raise ProfileError("matching Catalog runtime policy is required for Mindustry")

        install_path = require_absolute(
            context.get("install_path") or context.get("content_root") or instance.get("path"),
            "install_path",
        )
        state_root = require_absolute(context.get("instance_state_root"), "instance_state_root")
        runtime_root = str(Path(state_root) / "runtime")
        jar_path = str(Path(install_path) / "server-release.jar")
        ports = port_bindings(context)
        tcp = ports.get("game_tcp")
        udp = ports.get("game_udp")
        if not isinstance(tcp, dict) or str(tcp.get("protocol") or "").lower() != "tcp":
            raise ProfileError("Mindustry requires reserved game_tcp port")
        if not isinstance(udp, dict) or str(udp.get("protocol") or "").lower() != "udp":
            raise ProfileError("Mindustry requires reserved game_udp port")
        try:
            tcp_port = int(tcp.get("port"))
            udp_port = int(udp.get("port"))
        except (TypeError, ValueError) as exc:
            raise ProfileError("invalid Mindustry port allocation") from exc
        if tcp_port != udp_port:
            raise ProfileError("Mindustry TCP and UDP reservations must use the same port number")

        environment = context.get("environment") or {}
        if not isinstance(environment, dict):
            raise ProfileError("invalid Mindustry environment")

        return {
            "instance_id": instance_id,
            "agent_id": agent_id,
            "game_id": "mindustry",
            "environment_id": environment_id,
            "runtime_id": str(instance.get("runtime_id") or instance_id),
            "adapter": "windows-process",
            "working_directory": runtime_root,
            "executable": "java.exe",
            "arguments": ["-jar", jar_path, f"config port {tcp_port},host"],
            "environment": {
                **{str(k): str(v) for k, v in environment.items()},
                "CAPIVARA_INSTANCE_ID": instance_id,
                "CAPIVARA_GAME_ID": "mindustry",
                "CAPIVARA_GAME_PORT": str(tcp_port),
                "CAPIVARA_INSTANCE_STATE_ROOT": state_root,
            },
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "mindustry",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": state_root,
            "configuration_root": runtime_root,
            "writable_directories": [runtime_root],
            "seed_files": [],
            "seed_directories": [],
        }


__all__ = ["MindustryRuntimeProfile"]
