#!/usr/bin/env python3
"""FiveM Linux runtime profile with private server-data and credential-backed Cfx.re licensing."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text, require_within

_LAUNCHER = "/opt/capivara-agent/runtime/fivem_launch.py"


class FiveMRuntimeProfile(GameRuntimeProfile):
    game_ids = ("fivem", "fivem.stable")
    profile_version = 2

    def build_runtime_spec(self, instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        iid = require_text(instance.get("instance_id") or instance.get("id"), "instance_id")
        aid = require_text(instance.get("agent_id"), "agent_id")
        eid = require_text(instance.get("environment_id") or "fivem.stable", "environment_id")
        install = require_absolute(context.get("install_path") or context.get("content_root") or instance.get("path"), "install_path")
        state = require_absolute(context.get("instance_state_root"), "instance_state_root")
        policy = context.get("catalog_runtime_policy")
        if not isinstance(policy, dict) or str(policy.get("runtime_id") or "").strip() != eid:
            raise ProfileError("matching Catalog runtime policy is required for FiveM")

        server = require_within(install, str(Path(install) / "server" / "run.sh"), "executable")
        shared_data = require_within(install, str(Path(install) / "server-data"), "server-data")
        private_data = require_within(state, str(Path(state) / "fivem" / "server-data"), "private server-data")
        ports = port_bindings(context)
        game = ports.get("game")
        game_tcp = ports.get("game_tcp")
        if not isinstance(game, dict) or str(game.get("protocol") or "").lower() != "udp":
            raise ProfileError("FiveM requires a reserved UDP game port")
        if not isinstance(game_tcp, dict) or str(game_tcp.get("protocol") or "").lower() != "tcp":
            raise ProfileError("FiveM requires a reserved TCP game port")
        try:
            udp_port = int(game.get("port"))
            tcp_port = int(game_tcp.get("port"))
        except (TypeError, ValueError) as exc:
            raise ProfileError("FiveM endpoint ports must be numeric") from exc
        if udp_port != tcp_port:
            raise ProfileError("FiveM TCP and UDP endpoints must share the same port")

        raw_extra = context.get("arguments") or []
        if not isinstance(raw_extra, list):
            raise ProfileError("invalid FiveM runtime arguments")
        extra = [str(value) for value in raw_extra]
        if any("\x00" in value or "\n" in value or "\r" in value for value in extra):
            raise ProfileError("invalid FiveM runtime argument")
        forbidden = {"sv_licensekey", "+exec"}
        if any(value.lower() in forbidden for value in extra):
            raise ProfileError("FiveM runtime owns license and server.cfg arguments")

        return {
            "instance_id": iid,
            "agent_id": aid,
            "game_id": "fivem",
            "environment_id": eid,
            "runtime_id": str(instance.get("runtime_id") or iid),
            "adapter": "systemd",
            "working_directory": install,
            "executable": "/usr/bin/python3",
            "arguments": [_LAUNCHER, "--server", server, "--data", shared_data, "--license-credential", "FIVEM_LICENSE_KEY", *extra],
            "secret_refs": [{"name": "FIVEM_LICENSE_KEY", "ref": f"instance/{iid}/FIVEM_LICENSE_KEY", "target": "file"}],
            "environment": {"CAPIVARA_INSTANCE_ID": iid, "CAPIVARA_GAME_ID": "fivem"},
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "fivem",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": state,
            "configuration_root": private_data,
            "writable_directories": [str(Path(state) / "fivem")],
            "seed_files": [],
            "seed_directories": [
                {"source": "server-data", "target": "fivem/server-data", "optional": False}
            ],
            "bind_paths": [
                {"source": "fivem/server-data", "target": "server-data"}
            ],
        }


__all__ = ["FiveMRuntimeProfile"]
