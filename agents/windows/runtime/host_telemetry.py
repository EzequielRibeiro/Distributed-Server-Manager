#!/usr/bin/env python3
"""Windows host/process telemetry for the Capivara Agent.

The collector uses only the Python standard library plus native Windows APIs.
Returned keys intentionally mirror the platform-neutral telemetry contract
consumed by the Controller.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import shutil
import subprocess
import time
from typing import Any

_previous_cpu: tuple[int, int] | None = None
_previous_network: tuple[float, int, int] | None = None
_previous_process: tuple[float, float] | None = None
_previous_disk: tuple[float, int, int, int, int] | None = None


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


def _filetime_value(value: FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _run_powershell_json(script: str, timeout: int = 12) -> Any:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return json.loads(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


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


def _disk_raw_totals() -> tuple[int, int, int, int] | None:
    """Read monotonic disk counters from the Windows raw PerfDisk provider.

    Some storage drivers/hypervisors expose the formatted provider but keep its
    per-second fields at zero. The raw provider still advances cumulative byte
    and operation counters, so deriving rates from deltas is more portable.
    """
    script = r"""
$ErrorActionPreference='Stop'
$items = @(Get-CimInstance Win32_PerfRawData_PerfDisk_PhysicalDisk -ErrorAction Stop)
$total = $items | Where-Object { $_.Name -eq '_Total' } | Select-Object -First 1
if ($null -ne $total) {
  $readBytes = [int64]$total.DiskReadBytesPersec
  $writeBytes = [int64]$total.DiskWriteBytesPersec
  $reads = [int64]$total.DiskReadsPersec
  $writes = [int64]$total.DiskWritesPersec
} else {
  $readBytes = 0L
  $writeBytes = 0L
  $reads = 0L
  $writes = 0L
  foreach ($item in $items) {
    if ($item.Name -eq '_Total') { continue }
    $readBytes += [int64]$item.DiskReadBytesPersec
    $writeBytes += [int64]$item.DiskWriteBytesPersec
    $reads += [int64]$item.DiskReadsPersec
    $writes += [int64]$item.DiskWritesPersec
  }
}
@{
  read_bytes=$readBytes
  write_bytes=$writeBytes
  reads=$reads
  writes=$writes
} | ConvertTo-Json -Compress
"""
    payload = _run_powershell_json(script)
    if not isinstance(payload, dict):
        return None
    try:
        return (
            int(payload.get("read_bytes", 0)),
            int(payload.get("write_bytes", 0)),
            int(payload.get("reads", 0)),
            int(payload.get("writes", 0)),
        )
    except (TypeError, ValueError):
        return None


def _disk_activity() -> dict[str, float | None]:
    global _previous_disk
    now = time.monotonic()
    totals = _disk_raw_totals()
    empty = {
        "read_bytes_per_second": None,
        "write_bytes_per_second": None,
        "read_iops": None,
        "write_iops": None,
    }
    if totals is None:
        return empty

    read_bytes, write_bytes, reads, writes = totals
    previous = _previous_disk
    _previous_disk = (now, read_bytes, write_bytes, reads, writes)
    if previous is None:
        return empty

    elapsed = now - previous[0]
    if elapsed <= 0:
        return empty

    # Counter resets can happen after provider/device restart. Clamp negative
    # deltas to zero rather than publishing a bogus negative throughput.
    return {
        "read_bytes_per_second": round(max(0, read_bytes - previous[1]) / elapsed, 2),
        "write_bytes_per_second": round(max(0, write_bytes - previous[2]) / elapsed, 2),
        "read_iops": round(max(0, reads - previous[3]) / elapsed, 2),
        "write_iops": round(max(0, writes - previous[4]) / elapsed, 2),
    }


def _processor_queue_length() -> float | None:
    script = r"""
$ErrorActionPreference='Stop'
$system = Get-CimInstance Win32_PerfFormattedData_PerfOS_System -ErrorAction Stop |
  Select-Object -First 1
if ($null -eq $system) { $null | ConvertTo-Json -Compress }
else { ([double]$system.ProcessorQueueLength) | ConvertTo-Json -Compress }
"""
    value = _run_powershell_json(script)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _performance_snapshot() -> dict[str, float | None]:
    result = _disk_activity()
    result["processor_queue_length"] = _processor_queue_length()
    return result


def _disk(perf: dict[str, float | None] | None = None) -> dict[str, int | float | None]:
    perf = perf or {}
    root = os.environ.get("SystemDrive", "C:") + "\\"
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        total = used = free = usage_pct = None
    else:
        total = usage.total
        used = usage.used
        free = usage.free
        usage_pct = round(100.0 * usage.used / usage.total, 2) if usage.total else None
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "usage_pct": usage_pct,
        "read_bytes_per_second": perf.get("read_bytes_per_second"),
        "write_bytes_per_second": perf.get("write_bytes_per_second"),
        "read_iops": perf.get("read_iops"),
        "write_iops": perf.get("write_iops"),
    }


def _temperature_c() -> float | None:
    # ACPI thermal zones are not guaranteed to expose CPU temperature, and
    # hypervisors commonly expose no thermal sensor at all. Publish a value only
    # when Windows reports a plausible sensor reading; otherwise return None.
    script = r"""
$ErrorActionPreference='Stop'
$zones = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop)
$values = @()
foreach ($zone in $zones) {
  if ($null -eq $zone.CurrentTemperature) { continue }
  $c = ([double]$zone.CurrentTemperature / 10.0) - 273.15
  if ($c -ge -20 -and $c -le 150) { $values += $c }
}
if ($values.Count -eq 0) { $null | ConvertTo-Json -Compress }
else { (($values | Measure-Object -Average).Average) | ConvertTo-Json -Compress }
"""
    value = _run_powershell_json(script, timeout=8)
    if value is None:
        return None
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None
    if temperature < -20 or temperature > 150:
        return None
    return round(temperature, 1)


def _network_totals() -> tuple[int, int] | None:
    script = r"""
$ErrorActionPreference='Stop'
$items = @(Get-CimInstance Win32_PerfRawData_Tcpip_NetworkInterface -ErrorAction Stop |
  Where-Object { $_.Name -and $_.Name -notmatch 'Loopback' })
$rx = 0L
$tx = 0L
foreach ($item in $items) {
  $rx += [int64]$item.BytesReceivedPersec
  $tx += [int64]$item.BytesSentPersec
}
@{rx=$rx;tx=$tx} | ConvertTo-Json -Compress
"""
    payload = _run_powershell_json(script)
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get("rx", 0)), int(payload.get("tx", 0))
    except (TypeError, ValueError):
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


def _process_snapshot() -> dict[str, int | float | None]:
    pid = os.getpid()
    script = rf"""
$ErrorActionPreference='Stop'
$p = Get-Process -Id {pid} -ErrorAction Stop
@{{
  pid=[int]$p.Id
  working_set=[int64]$p.WorkingSet64
  threads=[int]$p.Threads.Count
  cpu_seconds=if ($null -eq $p.CPU) {{ $null }} else {{ [double]$p.CPU }}
}} | ConvertTo-Json -Compress
"""
    payload = _run_powershell_json(script, timeout=8)
    if not isinstance(payload, dict):
        return {
            "pid": pid,
            "memory_rss_bytes": None,
            "threads": None,
            "cpu_seconds": None,
        }
    return {
        "pid": int(payload.get("pid") or pid),
        "memory_rss_bytes": int(payload["working_set"]) if payload.get("working_set") is not None else None,
        "threads": int(payload["threads"]) if payload.get("threads") is not None else None,
        "cpu_seconds": float(payload["cpu_seconds"]) if payload.get("cpu_seconds") is not None else None,
    }


def _agent_process() -> dict[str, Any]:
    global _previous_process
    now = time.monotonic()
    snapshot = _process_snapshot()
    cpu_seconds = snapshot.pop("cpu_seconds", None)
    cpu_usage = None
    if isinstance(cpu_seconds, (int, float)):
        previous = _previous_process
        _previous_process = (now, float(cpu_seconds))
        if previous is not None:
            elapsed = now - previous[0]
            if elapsed > 0:
                cpu_delta = max(0.0, float(cpu_seconds) - previous[1])
                cores = max(1, int(os.cpu_count() or 1))
                cpu_usage = round(
                    max(0.0, min(100.0, 100.0 * cpu_delta / elapsed / cores)), 2
                )
    snapshot["cpu_usage_pct"] = cpu_usage
    return snapshot


def collect_host_telemetry() -> dict[str, Any]:
    """Collect one platform-neutral Windows telemetry sample."""
    perf = _performance_snapshot()
    return {
        "schema_version": 1,
        "collected_at_unix": round(time.time(), 3),
        "host": {
            "cpu_usage_pct": _cpu_usage_pct(),
            "memory": _memory(),
            "disk": _disk(perf),
            # Linux load average has no equivalent Windows semantic. Keep the
            # platform-neutral fields empty and publish Processor Queue Length
            # separately for Windows-specific pressure diagnostics.
            "load_average": {"1m": None, "5m": None, "15m": None},
            "processor_queue_length": perf.get("processor_queue_length"),
            "uptime_seconds": _uptime_seconds(),
            "network": _network(),
            "temperature_c": _temperature_c(),
        },
        "agent": _agent_process(),
        "top_processes": [],
    }


__all__ = ["collect_host_telemetry"]
