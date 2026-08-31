#!/usr/bin/env python3
"""Windows host/process telemetry for the Capivara Agent.

The collector uses only the Python standard library plus native Windows APIs.
Returned keys intentionally mirror agents/linux/runtime/host_telemetry.py so the
Controller can consume one platform-neutral telemetry contract.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
import time
from typing import Any

_previous_cpu: tuple[int, int] | None = None
_previous_network: tuple[float, int, int] | None = None
_previous_process: tuple[float, int] | None = None


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _filetime_value(value: FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _cpu_times() -> tuple[int, int] | None:
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
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
    busy = max(0, delta_total - delta_idle)
    return round(max(0.0, min(100.0, 100.0 * busy / delta_total)), 2)


def _memory() -> dict[str, int | float | None]:
    state = MEMORYSTATUSEX()
    state.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
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
    root = os.environ.get("SystemDrive", "C:") + "\\"
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
        "read_bytes_per_second": None,
        "write_bytes_per_second": None,
        "read_iops": None,
        "write_iops": None,
    }


def _network_totals() -> tuple[int, int] | None:
    script = r"""
$ErrorActionPreference='Stop'
$stats = Get-NetAdapterStatistics -ErrorAction Stop
$rx = 0L
$tx = 0L
foreach ($item in $stats) {
  $rx += [int64]$item.ReceivedBytes
  $tx += [int64]$item.SentBytes
}
Write-Output ($rx.ToString() + ',' + $tx.ToString())
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        line = completed.stdout.strip().splitlines()[-1]
        rx_text, tx_text = line.split(",", 1)
        return int(rx_text), int(tx_text)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _network() -> dict[str, int | float | None]:
    global _previous_network
    now = time.monotonic()
    totals = _network_totals()
    if totals is None:
        return {
            "rx_bytes": None,
            "tx_bytes": None,
            "rx_bytes_per_second": None,
            "tx_bytes_per_second": None,
        }
    rx, tx = totals
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


def _uptime_seconds() -> float | None:
    try:
        return round(float(ctypes.windll.kernel32.GetTickCount64()) / 1000.0, 1)
    except Exception:
        return None


def _process_times_100ns() -> int | None:
    creation = FILETIME()
    exit_time = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    try:
        ok = ctypes.windll.kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
    except Exception:
        return None
    if not ok:
        return None
    return _filetime_value(kernel) + _filetime_value(user)


def _process_cpu_pct() -> float | None:
    global _previous_process
    now = time.monotonic()
    total = _process_times_100ns()
    if total is None:
        return None
    previous = _previous_process
    _previous_process = (now, total)
    if previous is None:
        return None
    elapsed = now - previous[0]
    if elapsed <= 0:
        return None
    cpu_seconds = max(0.0, (total - previous[1]) / 10_000_000.0)
    cores = max(1, int(os.cpu_count() or 1))
    return round(max(0.0, min(100.0, 100.0 * cpu_seconds / elapsed / cores)), 2)


def _process_memory_rss() -> int | None:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
    except Exception:
        return None
    return int(counters.WorkingSetSize) if ok else None


def _thread_count() -> int | None:
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$p=Get-Process -Id $PID; [Console]::Out.Write($p.Threads.Count)",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        return int(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _agent_process() -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "cpu_usage_pct": _process_cpu_pct(),
        "memory_rss_bytes": _process_memory_rss(),
        "threads": _thread_count(),
    }


def collect_host_telemetry() -> dict[str, Any]:
    """Collect one platform-neutral Windows telemetry sample."""
    return {
        "schema_version": 1,
        "collected_at_unix": round(time.time(), 3),
        "host": {
            "cpu_usage_pct": _cpu_usage_pct(),
            "memory": _memory(),
            "disk": _disk(),
            "load_average": {"1m": None, "5m": None, "15m": None},
            "uptime_seconds": _uptime_seconds(),
            "network": _network(),
            "temperature_c": None,
        },
        "agent": _agent_process(),
        "top_processes": [],
    }


__all__ = ["collect_host_telemetry"]
