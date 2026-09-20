#!/usr/bin/env python3
"""Dispatch generic native restart commands to game-specific Agent adapters."""
from __future__ import annotations

from typing import Any

from dayz_native_restart_client import (
    clear_result as clear_dayz_result,
    handle_command as handle_dayz_command,
    read_result as read_dayz_result,
)

_SUPPORTED = {
    ("dayz", "dayz-shutdown-messages"): handle_dayz_command,
}


def handle_command(
    config: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    game_id = str(command.get("game_id") or "").strip().lower()
    strategy = str(command.get("strategy") or "native").strip().lower()
    handler = _SUPPORTED.get((game_id, strategy))
    if handler is None:
        command_id = str(command.get("command_id") or "").strip()
        instance_id = str(command.get("instance_id") or "").strip() or None
        return {
            "command_id": command_id,
            "instance_id": instance_id,
            "status": "failed",
            "error": f"unsupported native restart adapter: {game_id}/{strategy}",
        }
    return handler(config, command)


def read_result() -> dict[str, Any] | None:
    # DayZ is the first adapter. Additional game adapters join this fan-in.
    return read_dayz_result()


def clear_result(command_id: str) -> None:
    clear_dayz_result(command_id)


__all__ = ["clear_result", "handle_command", "read_result"]
