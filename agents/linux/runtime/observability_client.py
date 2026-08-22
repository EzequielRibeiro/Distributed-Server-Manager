#!/usr/bin/env python3
"""Portable Linux Agent observability collection without external dependencies."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sample(agent_id: str, name: str, value: float, unit: str = "1", *, metric_type: str = "gauge", instance_id: str | None = None, dimensions: dict[str, str] | None = None, collected_at: str | None = None) -> dict[str, Any]:
    return {
        "metric_name": name,
        "metric_type": metric_type,
        "scope_type": "instance" if instance_id else "agent",
        "agent_id": agent_id,
        "instance_id": instance_id,
        "value": float(value),
        "unit": unit,
        "dimensions": dimensions or {},
        "collected_at": collected_at or _now(),
    }


def _meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, rest = line.split(":", 1)
            parts = rest.split()
            if parts:
                result[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        pass
    return result


def _network() -> list[tuple[str, int, int]]:
    values: list[tuple[str, int, int]] = []
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
        for line in lines:
            name, data = line.split(":", 1)
            fields = data.split()
            values.append((name.strip(), int(fields[0]), int(fields[8])))
    except (OSError, ValueError, IndexError):
        pass
    return values


def collect_observability(config: dict[str, Any], *, instance_health: list[dict[str, Any]] | None = None, runtime_metrics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    agent_id = str(config.get("agent_id") or "").strip()
    if not agent_id:
        return []
    at = _now()
    samples: list[dict[str, Any]] = []
    try:
        load1, load5, load15 = os.getloadavg()
        cores = max(1, int(os.cpu_count() or 1))
        samples.extend([
            _sample(agent_id, "system.load.1", load1, "load", collected_at=at),
            _sample(agent_id, "system.load.5", load5, "load", collected_at=at),
            _sample(agent_id, "system.load.15", load15, "load", collected_at=at),
            _sample(agent_id, "system.load.per_core", load1 / cores, "ratio", collected_at=at),
        ])
    except (OSError, AttributeError):
        samples.append(_sample(agent_id, "system.load.per_core", 0, "ratio", collected_at=at))
    mem = _meminfo()
    total = mem.get("MemTotal")
    available = mem.get("MemAvailable")
    if total:
        samples.append(_sample(agent_id, "memory.total_bytes", total, "bytes", collected_at=at))
        if available is not None:
            samples.append(_sample(agent_id, "memory.available_bytes", available, "bytes", collected_at=at))
            samples.append(_sample(agent_id, "memory.used_ratio", (total - available) / total, "ratio", collected_at=at))
    try:
        disk = shutil.disk_usage("/")
        samples.extend([
            _sample(agent_id, "disk.root.total_bytes", disk.total, "bytes", collected_at=at),
            _sample(agent_id, "disk.root.free_bytes", disk.free, "bytes", collected_at=at),
            _sample(agent_id, "disk.root.used_ratio", disk.used / disk.total if disk.total else 0, "ratio", collected_at=at),
        ])
    except OSError:
        pass
    try:
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        samples.append(_sample(agent_id, "system.uptime_seconds", uptime, "seconds", collected_at=at))
    except (OSError, ValueError, IndexError):
        pass
    for interface, rx, tx in _network():
        dimensions = {"interface": interface}
        samples.append(_sample(agent_id, "network.receive_bytes", rx, "bytes", metric_type="counter", dimensions=dimensions, collected_at=at))
        samples.append(_sample(agent_id, "network.transmit_bytes", tx, "bytes", metric_type="counter", dimensions=dimensions, collected_at=at))
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        try:
            celsius = float(zone.read_text(encoding="utf-8").strip()) / 1000.0
        except (OSError, ValueError):
            continue
        samples.append(_sample(agent_id, "temperature.celsius", celsius, "celsius", dimensions={"zone": zone.parent.name}, collected_at=at))
    health_map = {"healthy": 1.0, "transitioning": 0.5, "unknown": -1.0, "degraded": 0.0}
    for item in instance_health or []:
        instance_id = str(item.get("instance_id") or "").strip()
        if not instance_id:
            continue
        health = str(item.get("health") or "unknown")
        samples.append(_sample(agent_id, "instance.health", health_map.get(health, -1.0), "state", instance_id=instance_id, dimensions={"health": health, "desired_state": str(item.get("desired_state") or "unknown"), "observed_state": str(item.get("observed_state") or "unknown")}, collected_at=at))
    for name, value in (runtime_metrics or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            samples.append(_sample(agent_id, "capivara.runtime." + str(name).lower().replace("_", "."), float(value), "1", metric_type="counter", collected_at=at))
    return samples[:2000]


__all__ = ["collect_observability"]
