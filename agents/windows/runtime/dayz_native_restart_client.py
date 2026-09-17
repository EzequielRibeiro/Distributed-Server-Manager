#!/usr/bin/env python3
"""Execute typed DayZ native restart preparation commands on Windows Agent."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
AGENT_DIR = RUNTIME_DIR.parent
COMMON_DIR = AGENT_DIR.parent / "common"

for candidate in (RUNTIME_DIR, COMMON_DIR):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from dayz_messages import (
    deadline_minutes_for_due,
    materialize_shutdown_messages_xml,
    native_restart_plan,
)
from instance_runtime import get_instance

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(
    os.environ.get(
        "CAPIVARA_AGENT_STATE_DIR",
        PROGRAM_DATA / "CapivaraAgent" / "state",
    )
)
RESULT_DIR = STATE_DIR / "dayz-native-restart-results"
HISTORY_DIR = STATE_DIR / "dayz-native-restart-history"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token(value: Any, label: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    if len(value) > 191:
        raise ValueError(f"invalid {label}")
    if not all(ch.isalnum() or ch in "._-" for ch in value):
        raise ValueError(f"invalid {label}")
    return value


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")

    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _history(command_id: str) -> Path:
    return HISTORY_DIR / f"{_token(command_id, 'command_id')}.json"


def _result(command_id: str) -> Path:
    return RESULT_DIR / f"{_token(command_id, 'command_id')}.json"


def handle_command(
    config: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    command_id = _token(command.get("command_id"), "command_id")

    previous = _read(_history(command_id))
    if previous is not None:
        _write(_result(command_id), previous)
        return previous

    instance_id = str(command.get("instance_id") or "").strip()

    try:
        instance_id = _token(instance_id, "instance_id")

        record = get_instance(instance_id)
        if record is None:
            raise LookupError(f"instance not found: {instance_id}")

        local_agent = str(config.get("agent_id") or "").strip()
        record_agent = str(record.get("agent_id") or "").strip()

        if not local_agent or record_agent != local_agent:
            raise PermissionError("instance belongs to another Agent")

        if str(record.get("game_id") or "").strip().lower() != "dayz":
            raise ValueError("native restart command requires DayZ instance")

        due_at = command.get("due_at")
        deadline_minutes = deadline_minutes_for_due(due_at)

        plan = native_restart_plan(
            record,
            deadline_minutes,
        )

        materialize_shutdown_messages_xml(
            Path(plan.messages_path),
            plan.message,
        )

        result = {
            "command_id": command_id,
            "instance_id": instance_id,
            "status": "completed",
            "result": {
                "schema_version": 1,
                "kind": "CapivaraDayZNativeRestartPrepared",
                "instance_id": instance_id,
                "mission": plan.mission,
                "deadline_minutes": deadline_minutes,
                "materialized": True,
                "due_at": str(due_at),
            },
            "generated_at": _now(),
        }

    except Exception as exc:
        result = {
            "command_id": command_id,
            "instance_id": instance_id or None,
            "status": "failed",
            "error": str(exc)[:2000],
            "generated_at": _now(),
        }

    _write(_history(command_id), result)
    _write(_result(command_id), result)
    return result


def read_result() -> dict[str, Any] | None:
    try:
        paths = sorted(RESULT_DIR.glob("*.json"))
    except OSError:
        paths = []

    for path in paths:
        value = _read(path)
        if value:
            return value

    return None


def clear_result(command_id: str) -> None:
    try:
        _result(command_id).unlink()
    except FileNotFoundError:
        pass


__all__ = [
    "clear_result",
    "handle_command",
    "read_result",
]
