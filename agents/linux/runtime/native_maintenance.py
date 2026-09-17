#!/usr/bin/env python3
"""Typed game-native maintenance operations for Linux Agent."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

COMMON = Path(__file__).resolve().parents[2] / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from palworld_rest_console import PalworldConsoleError, execute


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

    raise NativeMaintenanceError(
        f"game {game or 'unknown'} does not support typed native save"
    )


__all__ = [
    "NativeMaintenanceError",
    "broadcast",
    "save",
]
