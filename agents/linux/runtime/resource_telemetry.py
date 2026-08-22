#!/usr/bin/env python3
"""Best-effort Linux resource telemetry for the Capivara Agent.

Only Python's standard library and procfs/systemd are used so the Agent keeps
its zero-extra-runtime-dependency contract. Values are observational and must
never affect placement or lifecycle directly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CPU_SAMPLE: tuple[int, int] | None = None
_PROCESS_SAMPLES: dict[str, tuple[float, float]] = {}
_SYSTEMD_CPU_NS: dict[str, tuple[int, float]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 2)))


def _cpu_ticks() -> tuple[int, int] | None:
    try:
        values = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        ticks = [int(item) for item in values]
    except (OSError, ValueError, IndexError):
        return None
    if len(ticks) < 4:
        return None
    total = sum(ticks)
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return total, idle


def _host_cpu_percent() -> float | None:
    global _CPU_SAMPLE
    current = _cpu_ticks()
    if current is None:
        return None
    previous = _CPU_SAMPLE
    _CPU_SAMPLE = current
    if previous is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    return _clamp((total_delta - idle_delta) * 100.0 / total_delta)


def _memory() -> dict[str, int | float | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable", "MemFree"}:
                values[key] = int(rest.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    total = values.get("MemTotal")
    available = values.get("MemAvailable", values.get("MemFree"))
    used = max(0, total - available) if total is not None and available is not None else None
    percent = _clamp(used * 100.0 / total) if used is not None and total else None
    return {"total_bytes": total, "available_bytes": available, "used_bytes": used, "used_percent": percent}


def _load() -> dict[str, float | None]:
    try:
        one, five, fifteen = os.getloadavg()
        return {"load1": round(one, 2), "load5": round(five, 2), "load15": round(fifteen, 2)}
    except (AttributeError, OSError):
        return {"load1": None, "load5": None, "load15": None}


def _uptime_seconds() -> float | None:
    try:
        return round(float(Path("/proc/uptime").read_text().split()[0]), 2)
    except (OSError, ValueError, IndexError):
        return None


def _network_totals() -> dict[str, int]:
    rx = tx = 0
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
        for line in lines:
            name, _, data = line.partition(":")
            if name.strip() == "lo":
                continue
            fields = data.split()
            if len(fields) >= 9:
                rx += int(fields[0]); tx += int(fields[8])
    except (OSError, ValueError):
        pass
    return {"rx_bytes": rx, "tx_bytes": tx}


def collect_host_telemetry() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    return {
        "collected_at": _now(),
        "cpu_percent": _host_cpu_percent(),
        "logical_cores": os.cpu_count(),
        "memory": _memory(),
        "storage": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "used_percent": _clamp(disk.used * 100.0 / disk.total) if disk.total else None,
        },
        "load": _load(),
        "uptime_seconds": _uptime_seconds(),
        "network": _network_totals(),
    }


def _linux_process(pid: int, key: str) -> dict[str, Any]:
    if pid <= 0:
        return {"pid": None, "cpu_percent": None, "rss_bytes": None, "threads": None}
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines()
        process_seconds = (int(stat[13]) + int(stat[14])) / float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
        rss_bytes = int(statm[1]) * int(os.sysconf("SC_PAGE_SIZE"))
        threads = None
        for line in status:
            if line.startswith("Threads:"):
                threads = int(line.split()[1]); break
    except (OSError, ValueError, IndexError, KeyError):
        return {"pid": pid, "cpu_percent": None, "rss_bytes": None, "threads": None}
    now = time.monotonic()
    previous = _PROCESS_SAMPLES.get(key)
    _PROCESS_SAMPLES[key] = (process_seconds, now)
    cpu = None
    if previous and now > previous[1]:
        cores = max(1, int(os.cpu_count() or 1))
        cpu = _clamp((process_seconds - previous[0]) * 100.0 / (now - previous[1]) / cores)
    return {"pid": pid, "cpu_percent": cpu, "rss_bytes": rss_bytes, "threads": threads}


def collect_agent_telemetry() -> dict[str, Any]:
    result = _linux_process(os.getpid(), "@agent")
    result["collected_at"] = _now()
    return result


def _systemd_values(instance_id: str) -> dict[str, str]:
    unit = f"capivara-instance-{instance_id}.service"
    properties = ["MainPID", "ActiveState", "SubState", "MemoryCurrent", "CPUUsageNSec", "TasksCurrent", "IOReadBytes", "IOWriteBytes"]
    try:
        completed = subprocess.run(
            ["systemctl", "show", unit, *[f"--property={item}" for item in properties], "--no-pager"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value
    return values


def _number(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        return int(text) if text and text not in {"[not set]", "infinity"} else None
    except ValueError:
        return None


def collect_instance_resources(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    now = time.monotonic()
    for item in instances:
        instance_id = str(item.get("instance_id") or "").strip()
        if not instance_id:
            continue
        values = _systemd_values(instance_id)
        pid = _number(values.get("MainPID")) or 0
        memory = _number(values.get("MemoryCurrent"))
        cpu_ns = _number(values.get("CPUUsageNSec"))
        cpu = None
        previous = _SYSTEMD_CPU_NS.get(instance_id)
        if cpu_ns is not None:
            _SYSTEMD_CPU_NS[instance_id] = (cpu_ns, now)
            if previous and now > previous[1]:
                cores = max(1, int(os.cpu_count() or 1))
                cpu = _clamp((cpu_ns - previous[0]) / 1_000_000_000 * 100.0 / (now - previous[1]) / cores)
        if memory is None and pid:
            memory = _linux_process(pid, f"instance:{instance_id}").get("rss_bytes")
        result.append({
            "instance_id": instance_id,
            "game_id": item.get("game_id"),
            "observed_state": values.get("ActiveState") or item.get("observed_state") or "unknown",
            "pid": pid or None,
            "cpu_percent": cpu,
            "memory_bytes": memory,
            "tasks": _number(values.get("TasksCurrent")),
            "io_read_bytes": _number(values.get("IOReadBytes")),
            "io_write_bytes": _number(values.get("IOWriteBytes")),
            "collected_at": _now(),
        })
    return result


__all__ = ["collect_agent_telemetry", "collect_host_telemetry", "collect_instance_resources"]
