#!/usr/bin/env python3
"""FiveM Linux runtime profile with credential-backed Cfx.re license injection."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GameRuntimeProfile, ProfileError, port_bindings, require_absolute, require_text, require_within

_LAUNCHER = "/opt/capivara-agent/runtime/fivem_launch.py"


class FiveMRuntimeProfile(GameRuntimeProfile):
    game_ids = ("fivem", "fivem.stable")
    profile_version = 1

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
        data = require_within(install, str(Path(install) / "server-data"), "server-data")
        ports = port_bindings(context)
        game = ports.get("game")
        if not game:
            raise ProfileError("FiveM requires a reserved game port")

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
            "working_directory": data,
            "executable": "/usr/bin/python3",
            "arguments": [_LAUNCHER, "--server", server, "--data", data, "--license-credential", "FIVEM_LICENSE_KEY", *extra],
            "secret_refs": [{"name": "FIVEM_LICENSE_KEY", "ref": f"instance/{iid}/FIVEM_LICENSE_KEY", "target": "file"}],
            "environment": {"CAPIVARA_INSTANCE_ID": iid, "CAPIVARA_GAME_ID": "fivem"},
            "user": str(context.get("user") or "capivara-instance"),
            "desired_state": str(instance.get("desired_state") or context.get("desired_state") or "stopped"),
            "profile": "fivem",
            "profile_version": self.profile_version,
            "ports": ports,
            "instance_state_root": state,
            "configuration_root": str(Path(state) / "fivem"),
            "writable_directories": [str(Path(state) / "fivem")],
            "seed_files": [],
            "seed_directories": [],
        }


__all__ = ["FiveMRuntimeProfile"]
