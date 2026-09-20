#!/usr/bin/env python3
"""DayZ compatibility adapter over the generic native restart queue."""
from __future__ import annotations

from typing import Any

from native_restart_repository import (
    ACTIVE_STATES,
    FINAL_STATES,
    NativeRestartCommandConflict,
    NativeRestartRepository,
)

DayZNativeRestartCommandConflict = NativeRestartCommandConflict


class DayZNativeRestartRepository(NativeRestartRepository):
    """Preserve the DayZ-facing API while storing commands generically."""

    def enqueue(
        self,
        *,
        agent_id: str,
        instance_id: str,
        due_at: Any,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        return super().enqueue(
            agent_id=agent_id,
            instance_id=instance_id,
            due_at=due_at,
            strategy="dayz-shutdown-messages",
            payload={"schema_version": 1, "kind": "CapivaraDayZNativeRestart"},
            requested_by=requested_by,
            required_game_id="dayz",
        )


__all__ = [
    "ACTIVE_STATES",
    "DayZNativeRestartCommandConflict",
    "DayZNativeRestartRepository",
    "FINAL_STATES",
]
