"""Typed game-native maintenance operations for Windows Agent."""

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

from source_rcon import SourceRconError, execute as execute_source_rcon
from minecraft_rcon_secret import MinecraftRconSecretError, read_password


class NativeMaintenanceError(RuntimeError):
    pass


def _minecraft_java(instance: dict[str, Any]) -> bool:
    return (
        str(instance.get("game_id") or "").strip().lower() == "minecraft"
        and str(instance.get("environment_id") or "")
        .strip()
        .lower()
        .startswith("minecraft.java.")
    )


def _rcon(instance: dict[str, Any], command: str) -> str:
    if not _minecraft_java(instance):
        raise NativeMaintenanceError(
            "runtime does not support typed Minecraft Java maintenance"
        )

    try:
        password = read_password(instance)

        binding = (
            instance.get("ports", {}).get("rcon")
            if isinstance(instance.get("ports"), dict)
            else None
        ) or {}

        if str(binding.get("protocol") or "").lower() != "tcp":
            raise NativeMaintenanceError(
                "Minecraft Java RCON reservation is unavailable"
            )

        port = int(binding.get("port") or 0)

        if not 1 <= port <= 65535:
            raise NativeMaintenanceError(
                "Minecraft Java RCON reservation is unavailable"
            )

        return execute_source_rcon(
            "127.0.0.1",
            port,
            password,
            command,
        )

    except NativeMaintenanceError:
        raise
    except (
        MinecraftRconSecretError,
        SourceRconError,
        TypeError,
        ValueError,
    ) as exc:
        raise NativeMaintenanceError(str(exc)) from exc


def broadcast(
    instance: dict[str, Any],
    message: str,
    *,
    priority: str = "normal",
) -> dict[str, Any]:
    output = _rcon(
        instance,
        f"say {message}",
    )

    return {
        "game_id": "minecraft",
        "transport": "minecraft-rcon",
        "operation": "broadcast",
        "priority": str(priority),
        "output": [output] if output else [],
    }


def save(instance: dict[str, Any]) -> dict[str, Any]:
    output = _rcon(
        instance,
        "save-all flush",
    )

    return {
        "game_id": "minecraft",
        "transport": "minecraft-rcon",
        "operation": "save",
        "output": [output] if output else [],
    }


__all__ = [
    "NativeMaintenanceError",
    "broadcast",
    "save",
]
