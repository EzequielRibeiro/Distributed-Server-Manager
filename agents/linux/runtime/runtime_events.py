#!/usr/bin/env python3
"""Durable local producer queue for Universal Event Platform ingestion."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EVENT_RELATIVE_PATH = Path("events") / "instance-runtime.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_path(state_dir: Path) -> Path:
    path = Path(state_dir) / EVENT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def emit_runtime_event(
    state_dir: Path,
    event_type: str,
    *,
    instance_id: str,
    agent_id: str,
    data: dict[str, Any] | None = None,
    severity: str = "info",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "kind": "CapivaraRuntimeEvent",
        "event_id": str(uuid.uuid4()),
        "event_type": str(event_type).upper(),
        "type": str(event_type).upper(),
        "producer": "instance-runtime",
        "source": "agent.runtime",
        "instance_id": str(instance_id),
        "agent_id": str(agent_id),
        "severity": str(severity).lower(),
        "occurred_at": _now(),
        "correlation_id": correlation_id,
        "data": dict(data or {}),
    }
    path = _event_path(Path(state_dir))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return payload


def read_runtime_events(state_dir: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    path = _event_path(Path(state_dir))
    if not path.exists():
        return []
    bounded = max(1, min(int(limit), 1000))
    result: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines[:bounded]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def acknowledge_runtime_events(state_dir: Path, event_ids: Iterable[str]) -> int:
    """Atomically remove only Controller-acknowledged events from the local queue."""
    accepted = {str(value).strip() for value in event_ids if str(value).strip()}
    if not accepted:
        return 0
    path = _event_path(Path(state_dir))
    if not path.exists():
        return 0

    kept: list[str] = []
    removed = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        event_id = str(value.get("event_id") or "").strip() if isinstance(value, dict) else ""
        if event_id and event_id in accepted:
            removed += 1
        else:
            kept.append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".runtime-events-", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            if kept:
                stream.write("\n".join(kept) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return removed


__all__ = ["emit_runtime_event", "read_runtime_events", "acknowledge_runtime_events"]
