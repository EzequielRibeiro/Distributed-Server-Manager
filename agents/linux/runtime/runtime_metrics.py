#!/usr/bin/env python3
"""Small durable runtime metrics producer for Agent observability."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import instance_runtime
from host_telemetry import collect_host_telemetry
from observability_client import collect_observability
from storage_pools import pool_inventory


def _path() -> Path:
    return Path(instance_runtime.STATE_DIR) / "metrics" / "instance-runtime.json"


def _agent_config() -> dict[str, Any]:
    path = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


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


def _storage_pool_samples(pools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    fields = (
        ("total_bytes", "total_bytes"),
        ("free_bytes", "free_bytes"),
        ("usable_bytes", "usable_bytes"),
        ("reserve_bytes", "reserve_bytes"),
    )
    for pool in pools:
        dimensions = {
            "storage_pool_id": str(pool.get("id") or "unknown"),
            "storage_class": str(pool.get("storage_class") or "standard"),
            "health": str(pool.get("health") or "unknown"),
            "enabled": str(bool(pool.get("enabled", True))).lower(),
            "default": str(bool(pool.get("default", False))).lower(),
        }
        for field, suffix in fields:
            value = pool.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                samples.append({
                    "metric_name": f"capivara.storage.pool.{suffix}",
                    "metric_type": "gauge",
                    "value": value,
                    "unit": "bytes",
                    "scope_type": "agent",
                    "dimensions": dimensions,
                })
        priority = pool.get("priority")
        if isinstance(priority, (int, float)) and not isinstance(priority, bool):
            samples.append({
                "metric_name": "capivara.storage.pool.priority",
                "metric_type": "gauge",
                "value": priority,
                "unit": "1",
                "scope_type": "agent",
                "dimensions": dimensions,
            })
        samples.append({
            "metric_name": "capivara.storage.pool.health",
            "metric_type": "gauge",
            "value": 1 if pool.get("health") == "online" else 0,
            "unit": "state",
            "scope_type": "agent",
            "dimensions": dimensions,
        })
    return samples


def snapshot(*, queue_depth: dict[str, int] | None = None) -> dict[str, Any]:
    payload = _read()
    if queue_depth is not None:
        payload["queue_depth"] = {str(key): max(0, int(value)) for key, value in queue_depth.items()}
    samples = collect_observability({"agent_id": "local"})
    for sample in samples:
        sample.pop("agent_id", None)

    config = _agent_config()
    pools: list[dict[str, Any]] = []
    if config:
        try:
            pools = pool_inventory(config)
        except (OSError, ValueError):
            pools = []
    samples.extend(_storage_pool_samples(pools))
    payload["observability_samples"] = samples

    telemetry = collect_host_telemetry()
    if pools:
        telemetry["storage_pools"] = pools
    payload["telemetry"] = telemetry
    payload["storage_pools"] = pools
    return payload


__all__ = ["increment", "observe_duration", "snapshot"]
