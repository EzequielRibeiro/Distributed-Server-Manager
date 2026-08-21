#!/usr/bin/env python3
"""Structured local producer for instance-runtime events consumed by the event platform."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def emit_runtime_event(state_dir: Path, event_type: str, *, instance_id: str, agent_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "kind": "CapivaraEvent",
        "type": str(event_type),
        "producer": "instance-runtime",
        "instance_id": str(instance_id),
        "agent_id": str(agent_id),
        "occurred_at": _now(),
        "data": dict(data or {}),
    }
    path = Path(state_dir) / "events" / "instance-runtime.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return payload


__all__ = ["emit_runtime_event"]
