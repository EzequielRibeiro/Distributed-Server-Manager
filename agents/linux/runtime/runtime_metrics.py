#!/usr/bin/env python3
"""Small durable runtime metrics producer for Agent observability."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import instance_runtime
from observability_client import collect_observability


def _path() -> Path:
    return Path(instance_runtime.STATE_DIR) / "metrics" / "instance-runtime.json"


def _read() -> dict[str, Any]:
    try:
        value = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": 1, "kind": "CapivaraInstanceRuntimeMetrics", "counters": {}, "durations_ms": {}}
    return value if isinstance(value, dict) else {"schema_version": 1, "kind": "CapivaraInstanceRuntimeMetrics", "counters": {}, "durations_ms": {}}


def _write(payload: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def increment(name: str, amount: int = 1) -> None:
    payload = _read()
    counters = payload.setdefault("counters", {})
    counters[name] = int(counters.get(name, 0)) + int(amount)
    _write(payload)


def observe_duration(name: str, duration_ms: int) -> None:
    payload = _read()
    durations = payload.setdefault("durations_ms", {})
    item = durations.setdefault(name, {"count": 0, "total": 0, "max": 0})
    value = max(0, int(duration_ms))
    item["count"] = int(item.get("count", 0)) + 1
    item["total"] = int(item.get("total", 0)) + value
    item["max"] = max(int(item.get("max", 0)), value)
    _write(payload)


def snapshot(*, queue_depth: dict[str, int] | None = None) -> dict[str, Any]:
    payload = _read()
    if queue_depth is not None:
        payload["queue_depth"] = {str(key): max(0, int(value)) for key, value in queue_depth.items()}
    samples = collect_observability({"agent_id": "local"})
    for sample in samples:
        sample.pop("agent_id", None)
    payload["observability_samples"] = samples
    return payload


__all__ = ["increment", "observe_duration", "snapshot"]
