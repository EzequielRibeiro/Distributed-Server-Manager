#!/usr/bin/env python3
"""Best-effort Windows resource telemetry for the Capivara Agent."""
from __future__ import annotations

import ctypes
import os
import shutil
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SYSTEM_CPU_SAMPLE: tuple[int, int] | None = None
_PROCESS_CPU_SAMPLES: dict[str, tuple[int, float]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 2)))


def _filetime_value(value) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _system_cpu_percent() -> float | None:
    global _SYSTEM_CPU_SAMPLE
    try:
        idle = wintypes.FILETIME(); kernel = wintypes.FILETIME(); user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        idle_v = _filetime_value(idle)
        total_v = _filetime_value(kernel) + _filetime_value(user)
    except Exception:
        return None
    previous = _SYSTEM_CPU_SAMPLE
    _SYSTEM_CPU_SAMPLE = (total_v, idle_v)
    if previous is None:
        return None
    total_delta = total_v - previous[0]
    idle_delta = idle_v - previous[1]
    if total_delta <= 0:
        return None
    return _clamp((total_delta - idle_delta) * 100.0 / total_delta)


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory() -> dict[str, int | float | None]:
    try:
        status = MEMORYSTATUSEX(); status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError
        total = int(status.ullTotalPhys); available = int(status.ullAvailPhys); used = max(0, total - available)
        return {"total_bytes": total, "available_bytes": available, "used_bytes": used, "used_percent": _clamp(used * 100.0 / total) if total else None}
    except Exception:
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None, "used_percent": None}


def collect_host_telemetry() -> dict[str, Any]:
    root = Path(os.environ.get("SystemDrive", "C:") + "\\")
    disk = shutil.disk_usage(root)
    try:
        uptime = round(float(ctypes.windll.kernel32.GetTickCount64()) / 1000.0, 2)
    except Exception:
        uptime = None
    return {
        "collected_at": _now(),
        "cpu_percent": _system_cpu_percent(),
        "logical_cores": os.cpu_count(),
        "memory": _memory(),
        "storage": {
            "total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free,
            "used_percent": _clamp(disk.used * 100.0 / disk.total) if disk.total else None,
        },
        "load": {"load1": None, "load5": None, "load15": None},
        "uptime_seconds": uptime,
        "network": {"rx_bytes": None, "tx_bytes": None},
    }


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _process(pid: int, key: str) -> dict[str, Any]:
    if pid <= 0:
        return {"pid": None, "cpu_percent": None, "rss_bytes": None, "threads": None}
    handle = None
    try:
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            raise OSError
        creation = wintypes.FILETIME(); exit_time = wintypes.FILETIME(); kernel = wintypes.FILETIME(); user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError
        process_100ns = _filetime_value(kernel) + _filetime_value(user)
        counters = PROCESS_MEMORY_COUNTERS_EX(); counters.cb = ctypes.sizeof(counters)
        rss = None
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            rss = int(counters.WorkingSetSize)
        now = time.monotonic(); previous = _PROCESS_CPU_SAMPLES.get(key); _PROCESS_CPU_SAMPLES[key] = (process_100ns, now)
        cpu = None
        if previous and now > previous[1]:
            cores = max(1, int(os.cpu_count() or 1))
            cpu = _clamp((process_100ns - previous[0]) / 10_000_000 * 100.0 / (now - previous[1]) / cores)
        return {"pid": pid, "cpu_percent": cpu, "rss_bytes": rss, "threads": None}
    except Exception:
        return {"pid": pid, "cpu_percent": None, "rss_bytes": None, "threads": None}
    finally:
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)


def collect_agent_telemetry() -> dict[str, Any]:
    result = _process(os.getpid(), "@agent")
    result["collected_at"] = _now()
    return result


def _instance_pid(instance_id: str) -> int | None:
    state_root = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "CapivaraAgent" / "state"))
    path = state_root / "runtime-processes" / f"{instance_id}.json"
    try:
        import json
        value = json.loads(path.read_text(encoding="utf-8"))
        return int(value.get("pid") or 0) or None
    except (OSError, ValueError, TypeError):
        return None


def collect_instance_resources(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in instances:
        instance_id = str(item.get("instance_id") or "").strip()
        if not instance_id:
            continue
        pid = _instance_pid(instance_id)
        process = _process(int(pid or 0), f"instance:{instance_id}")
        result.append({
            "instance_id": instance_id,
            "game_id": item.get("game_id"),
            "observed_state": item.get("observed_state") or ("running" if pid else "unknown"),
            "pid": pid,
            "cpu_percent": process.get("cpu_percent"),
            "memory_bytes": process.get("rss_bytes"),
            "tasks": process.get("threads"),
            "io_read_bytes": None,
            "io_write_bytes": None,
            "collected_at": _now(),
        })
    return result


__all__ = ["collect_agent_telemetry", "collect_host_telemetry", "collect_instance_resources"]
