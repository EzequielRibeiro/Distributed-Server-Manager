#!/usr/bin/env python3
"""Crash-consistent operation journal for mutating instance runtime work."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator

import instance_runtime
from runtime_lock import instance_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _root() -> Path:
    return Path(instance_runtime.STATE_DIR) / "instance-operations"


def _path(instance_id: str) -> Path:
    return _root() / f"{instance_runtime._token(instance_id, 'instance_id')}.json"


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def read_operation(instance_id: str) -> dict[str, Any] | None:
    try:
        value = json.loads(_path(instance_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def recover_interrupted_operations(config: dict[str, Any]) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    root = _root()
    try:
        paths = sorted(root.glob("*.json"))
    except OSError:
        return recovered
    local_agent = str(config.get("agent_id") or "").strip()
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict) or value.get("status") != "running":
            continue
        if str(value.get("agent_id") or local_agent) != local_agent:
            continue
        value["status"] = "interrupted"
        value["interrupted_at"] = _now()
        value["error"] = "Agent restarted before operation completion"
        _atomic(path, value)
        recovered.append(value)
    return recovered


@contextmanager
def runtime_operation(config: dict[str, Any], instance_id: str, operation: str, *, lock_timeout_seconds: float = 5.0) -> Iterator[dict[str, Any]]:
    agent_id = str(config.get("agent_id") or "").strip()
    if not agent_id:
        raise ValueError("agent_id is required")
    instance_id = instance_runtime._token(instance_id, "instance_id")
    operation = str(operation or "").strip()
    previous = read_operation(instance_id)
    started = time.monotonic()
    with instance_lock(instance_id, operation, timeout_seconds=lock_timeout_seconds):
        journal = {
            "schema_version": 1,
            "kind": "CapivaraInstanceRuntimeOperation",
            "agent_id": agent_id,
            "instance_id": instance_id,
            "operation": operation,
            "status": "running",
            "started_at": _now(),
            "previous_interrupted": bool(previous and previous.get("status") in {"running", "interrupted"}),
        }
        _atomic(_path(instance_id), journal)
        try:
            yield journal
        except Exception as exc:
            journal["status"] = "failed"
            journal["error"] = str(exc)[:2000]
            journal["finished_at"] = _now()
            journal["duration_ms"] = int((time.monotonic() - started) * 1000)
            _atomic(_path(instance_id), journal)
            raise
        else:
            journal["status"] = "completed"
            journal["finished_at"] = _now()
            journal["duration_ms"] = int((time.monotonic() - started) * 1000)
            _atomic(_path(instance_id), journal)


__all__ = ["read_operation", "recover_interrupted_operations", "runtime_operation"]
