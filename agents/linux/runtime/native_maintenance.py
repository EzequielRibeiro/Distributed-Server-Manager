#!/usr/bin/env python3
"""Typed game-native maintenance operations for Linux Agent."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_COMMON_CANDIDATES = (
    _HERE.parents[2] / "common",  # repository: agents/common
    _HERE.parents[1] / "common",  # installed Agent: <root>/common
)
COMMON = next(
    (path for path in _COMMON_CANDIDATES if path.is_dir()),
    _COMMON_CANDIDATES[0],
)
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from palworld_rest_console import PalworldConsoleError, execute
from source_rcon import SourceRconError, execute as execute_source_rcon
from minecraft_rcon_secret import MinecraftRconSecretError, read_password


class NativeMaintenanceError(RuntimeError):
    pass


def _game(instance: dict[str, Any]) -> str:
    return str(instance.get("game_id") or "").strip().lower()


def broadcast(
    instance: dict[str, Any],
    message: str,
    *,
    priority: str = "normal",
) -> dict[str, Any]:
    game = _game(instance)

    if game == "palworld":
        try:
            lines = execute(instance, f"/Broadcast {message}")
        except PalworldConsoleError as exc:
            raise NativeMaintenanceError(str(exc)) from exc

        return {
            "game_id": game,
            "transport": "palworld-rest",
            "operation": "broadcast",
            "priority": str(priority),
            "output": lines,
        }

    environment_id = str(instance.get("environment_id") or "").strip().lower()
    if game == "minecraft" and environment_id.startswith("minecraft.java."):
        if __import__("os").environ.get("CAPIVARA_NATIVE_COMMAND_UNIT_TEMPLATE"):
            from privileged_native_command import execute as privileged_execute
            result = privileged_execute(
                instance,
                "broadcast",
                message=message,
            )
            return {
                "game_id": game,
                "transport": "minecraft-rcon",
                "operation": "broadcast",
                "priority": str(priority),
                "output": list(result.get("output") or []),
            }

        try:
            password = read_password(instance)
            rcon = instance.get("ports", {}).get("rcon") or {}
            port = int(rcon.get("port") or 0)

            output = execute_source_rcon(
                "127.0.0.1",
                port,
                password,
                f"say {message}",
            )
        except (
            MinecraftRconSecretError,
            SourceRconError,
            TypeError,
            ValueError,
        ) as exc:
            raise NativeMaintenanceError(str(exc)) from exc

        return {
            "game_id": game,
            "transport": "minecraft-rcon",
            "operation": "broadcast",
            "priority": str(priority),
            "output": [output] if output else [],
        }

    raise NativeMaintenanceError(
        f"game {game or 'unknown'} does not support typed native broadcast"
    )


def save(instance: dict[str, Any]) -> dict[str, Any]:
    game = _game(instance)

    if game == "palworld":
        try:
            lines = execute(instance, "/Save")
        except PalworldConsoleError as exc:
            raise NativeMaintenanceError(str(exc)) from exc

        return {
            "game_id": game,
            "transport": "palworld-rest",
            "operation": "save",
            "output": lines,
        }

    environment_id = str(instance.get("environment_id") or "").strip().lower()
    if game == "minecraft" and environment_id.startswith("minecraft.java."):
        if __import__("os").environ.get("CAPIVARA_NATIVE_COMMAND_UNIT_TEMPLATE"):
            from privileged_native_command import execute as privileged_execute
            result = privileged_execute(
                instance,
                "save",
            )
            return {
                "game_id": game,
                "transport": "minecraft-rcon",
                "operation": "save",
                "output": list(result.get("output") or []),
            }

        try:
            password = read_password(instance)
            rcon = instance.get("ports", {}).get("rcon") or {}
            port = int(rcon.get("port") or 0)

            output = execute_source_rcon(
                "127.0.0.1",
                port,
                password,
                "save-all flush",
            )
        except (
            MinecraftRconSecretError,
            SourceRconError,
            TypeError,
            ValueError,
        ) as exc:
            raise NativeMaintenanceError(str(exc)) from exc

        return {
            "game_id": game,
            "transport": "minecraft-rcon",
            "operation": "save",
            "output": [output] if output else [],
        }

    raise NativeMaintenanceError(
        f"game {game or 'unknown'} does not support typed native save"
    )


__all__ = [
    "NativeMaintenanceError",
    "broadcast",
    "save",
]
