#!/usr/bin/env python3
"""Unprivileged bridge from heartbeat update command to privileged updater."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"


def stage_update_request(command: dict[str, Any]) -> bool:
    version = str(command.get("desired_version", "")).strip()
    channel = str(command.get("channel", "stable")).strip().lower()
    rollout_id = str(command.get("rollout_id", "")).strip()
    if not version or channel not in {"stable", "beta", "local/manual"}:
        return False
    existing = None
    try:
        existing = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if isinstance(existing, dict) and existing.get("desired_version") == version:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = REQUEST_PATH.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {
                "desired_version": version,
                "channel": channel,
                "rollout_id": rollout_id,
                "batch_number": command.get("batch_number"),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    temp.replace(REQUEST_PATH)
    return True


def read_update_result() -> dict[str, Any] | None:
    try:
        value = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def clear_update_result() -> None:
    try:
        RESULT_PATH.unlink()
    except FileNotFoundError:
        pass


__all__ = ["stage_update_request", "read_update_result", "clear_update_result"]
