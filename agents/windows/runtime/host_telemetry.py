#!/usr/bin/env python3
"""Windows host/process telemetry for the Capivara Agent.

The payload mirrors agents/linux/runtime/host_telemetry.py so the Controller and
Dashboard consume one platform-neutral telemetry contract. The collector uses
only the Python standard library plus built-in Windows PowerShell cmdlets.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

_previous_cpu: tuple[int, int] | None = None
_previous_network: tuple[float, int, int] | None = None
_previous_process: dict[int, tuple[float, float]] = {}


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _filetime_value(value: _FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _cpu_times() -> tuple[int, int] | None:
    idle = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
    except Exception:
        return None
    if not ok:
        return None
    idle_value = _filetime_value(idle)
    total_value = _filetime_value(kernel) + _filetime_value(user)
    return total_value, idle_value


def _cpu_usage_pct() -> float | None:
    global _previous_cpu
    current = _cpu_times()
    if current is None:
        return None
    previous = _previous_cpu
    _previous_cpu = current
    if previous is None:
        return None
    delta_total = current[0] - previous[0]
    delta_idle = current[1] - previous[1]
    if delta_total <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * (delta_total - delta_idle) / delta_total)), 2)


def _memory() -> dict[str, int | float | None]:
    state = _MEMORYSTATUSEX()
    state.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state))
    except Exception:
        ok = 0
    if not ok:
        return {
            "total_bytes": None,
            "used_bytes": None,
            "available_bytes": None,
            "usage_pct": None,
        }
    total = int(state.ullTotalPhys)
    available = int(state.ullAvailPhys)
    used = max(total - available, 0)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "usage_pct": round(100.0 * used / total, 2) if total else None,
    }


def _disk() -> dict[str, int | float | None]:
    root = str(Path(os.environ.get("SystemDrive", "C:")) / "\\")
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return {
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "usage_pct": None,
            "read_bytes_per_second": None,
            "write_bytes_per_second": None,
            "read_iops": None,
            "write_iops": None,
        }
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "usage_pct": round(100.0 * usage.used / usage.total, 2) if usage.total else None,
        # Disk I/O counters are intentionally reported unavailable until a
        # locale-independent Windows counter backend is added.
        "read_bytes_per_second": None,
        "write_bytes_per_second": None,
        "read_iops": None,
        "write_iops": None,
    }


def _uptime_seconds() -> float | None:
    try:
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return round(float(ctypes.windll.kernel32.GetTickCount64()) / 1000.0, 1)
    except Exception:
        return None


def _powershell_snapshot() -> dict[str, Any]:
    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
$processes = @(Get-Process | ForEach-Object {
    [pscustomobject]@{
        Id = $_.Id
        ProcessName = $_.ProcessName
        CPU = $_.CPU
        WorkingSet64 = $_.WorkingSet64
        ThreadsCount = $_.Threads.Count
    }
})
$adapters = @(Get-NetAdapterStatistics | ForEach-Object {
    [pscustomobject]@{
        ReceivedBytes = $_.ReceivedBytes
        SentBytes = $_.SentBytes
    }
})
[pscustomobject]@{ processes = $processes; adapters = $adapters } | ConvertTo-Json -Compress -Depth 4
'''.strip()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _network(adapters: Any) -> dict[str, int | float | None]:
    global _previous_network
    rows = adapters if isinstance(adapters, list) else []
    rx = tx = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            rx += int(row.get("ReceivedBytes") or 0)
            tx += int(row.get("SentBytes") or 0)
        except (TypeError, ValueError):
            continue
    now = time.monotonic()
    previous = _previous_network
    _previous_network = (now, rx, tx)
    rx_rate = tx_rate = None
    if previous is not None:
        elapsed = now - previous[0]
        if elapsed > 0:
            rx_rate = max(0.0, (rx - previous[1]) / elapsed)
            tx_rate = max(0.0, (tx - previous[2]) / elapsed)
    return {
        "rx_bytes": rx,
        "tx_bytes": tx,
        "rx_bytes_per_second": round(rx_rate, 2) if rx_rate is not None else None,
        "tx_bytes_per_second": round(tx_rate, 2) if tx_rate is not None else None,
    }


def _processes(rows: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now = time.monotonic()
    current_pid = os.getpid()
    logical_cores = max(int(os.cpu_count() or 1), 1)
    seen: set[int] = set()
    samples: list[dict[str, Any]] = []
    own: dict[str, Any] = {
        "pid": current_pid,
        "name": "python",
        "cpu_usage_pct": None,
        "memory_rss_bytes": None,
        "threads": None,
    }
    source = rows if isinstance(rows, list) else []
    for item in source:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("Id"))
        except (TypeError, ValueError):
            continue
        seen.add(pid)
        try:
            cpu_seconds = float(item.get("CPU") or 0.0)
        except (TypeError, ValueError):
            cpu_seconds = 0.0
        previous = _previous_process.get(pid)
        _previous_process[pid] = (now, cpu_seconds)
        cpu_pct = None
        if previous is not None:
            elapsed = now - previous[0]
            delta_cpu = cpu_seconds - previous[1]
            if elapsed > 0 and delta_cpu >= 0:
                # Normalize to host-wide percent (0..100), matching host CPU.
                cpu_pct = round(max(0.0, min(100.0, 100.0 * delta_cpu / elapsed / logical_cores)), 2)
        try:
            rss = int(item.get("WorkingSet64"))
        except (TypeError, ValueError):
            rss = None
        try:
            threads = int(item.get("ThreadsCount"))
        except (TypeError, ValueError):
            threads = None
        row = {
            "name": str(item.get("ProcessName") or "process"),
            "pid": pid,
            "cpu_usage_pct": cpu_pct,
            "memory_rss_bytes": rss,
            "threads": threads,
        }
        samples.append(row)
        if pid == current_pid:
            own = dict(row)
    for pid in list(_previous_process):
        if pid not in seen:
            _previous_process.pop(pid, None)
    samples.sort(key=lambda item: float(item.get("cpu_usage_pct") or 0.0), reverse=True)
    return own, samples[:5]


def collect_host_telemetry() -> dict[str, Any]:
    """Collect one platform-neutral Windows host telemetry sample."""
    snapshot = _powershell_snapshot()
    process, top_processes = _processes(snapshot.get("processes"))
    return {
        "schema_version": 1,
        "collected_at_unix": round(time.time(), 3),
        "host": {
            "cpu_usage_pct": _cpu_usage_pct(),
            "memory": _memory(),
            "disk": _disk(),
            "load_average": {"1m": None, "5m": None, "15m": None},
            "uptime_seconds": _uptime_seconds(),
            "network": _network(snapshot.get("adapters")),
            "temperature_c": None,
        },
        "agent": process,
        "top_processes": top_processes,
    }


__all__ = ["collect_host_telemetry"]
