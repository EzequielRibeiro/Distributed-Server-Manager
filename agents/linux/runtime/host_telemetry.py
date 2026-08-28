#!/usr/bin/env python3
"""Linux host/process telemetry for the Capivara Agent.

The collector intentionally uses procfs/sysfs and the Python standard library so
Agent packages do not need psutil. Returned keys are platform-neutral and may be
implemented by the Windows Agent with a different collector later.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

_PROC = Path("/proc")
_SYS = Path("/sys")
_CLOCK_TICKS = int(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
_PAGE_SIZE = int(os.sysconf("SC_PAGE_SIZE")) if hasattr(os, "sysconf") else 4096

_previous_cpu: tuple[int, int] | None = None
_previous_network: tuple[float, int, int] | None = None
_previous_disk_io: tuple[float, int, int, int, int] | None = None
_previous_process: dict[int, tuple[float, int]] = {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cpu_times() -> tuple[int, int] | None:
    line = _read_text(_PROC / "stat").splitlines()
    if not line or not line[0].startswith("cpu "):
        return None
    try:
        values = [int(value) for value in line[0].split()[1:]]
    except ValueError:
        return None
    total = sum(values)
    idle = (values[3] if len(values) > 3 else 0) + (values[4] if len(values) > 4 else 0)
    return total, idle


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
    values: dict[str, int] = {}
    for line in _read_text(_PROC / "meminfo").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        fields = raw.split()
        if not fields:
            continue
        try:
            values[key] = int(fields[0]) * 1024
        except ValueError:
            continue
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(total - available, 0)
    return {
        "total_bytes": total or None,
        "used_bytes": used if total else None,
        "available_bytes": available if total else None,
        "usage_pct": round(100.0 * used / total, 2) if total else None,
    }


def _disk() -> dict[str, int | float | None]:
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return {"total_bytes": None, "used_bytes": None, "free_bytes": None, "usage_pct": None}
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "usage_pct": round(100.0 * usage.used / usage.total, 2) if usage.total else None,
    }


def _disk_io_totals() -> tuple[int, int, int, int]:
    """Return cumulative read/write bytes and completed I/O operations.

    Linux /proc/diskstats reports sectors; Linux sectors are defined as
    512-byte units for this interface. Device-mapper, loop, ram and optical
    pseudo-devices are ignored to avoid obvious double counting.
    """
    read_bytes = write_bytes = read_ops = write_ops = 0

    for line in _read_text(_PROC / "diskstats").splitlines():
        fields = line.split()
        if len(fields) < 14:
            continue

        name = fields[2]

        if (
            name.startswith(("loop", "ram", "sr", "fd", "dm-"))
            or name.startswith("md")
        ):
            continue

        # Count whole physical/block devices, not their partitions.
        if (name.startswith(("sd", "vd", "xvd")) and name[-1:].isdigit()):
            continue
        if name.startswith("nvme") and "p" in name:
            continue
        if name.startswith("mmcblk") and "p" in name:
            continue

        try:
            reads_completed = int(fields[3])
            sectors_read = int(fields[5])
            writes_completed = int(fields[7])
            sectors_written = int(fields[9])
        except (ValueError, IndexError):
            continue

        read_ops += reads_completed
        write_ops += writes_completed
        read_bytes += sectors_read * 512
        write_bytes += sectors_written * 512

    return read_bytes, write_bytes, read_ops, write_ops


def _disk_io() -> dict[str, int | float | None]:
    global _previous_disk_io

    now = time.monotonic()
    read_bytes, write_bytes, read_ops, write_ops = _disk_io_totals()

    previous = _previous_disk_io
    _previous_disk_io = (
        now,
        read_bytes,
        write_bytes,
        read_ops,
        write_ops,
    )

    read_rate = write_rate = read_iops = write_iops = None

    if previous is not None:
        elapsed = now - previous[0]

        if elapsed > 0:
            read_rate = max(0.0, (read_bytes - previous[1]) / elapsed)
            write_rate = max(0.0, (write_bytes - previous[2]) / elapsed)
            read_iops = max(0.0, (read_ops - previous[3]) / elapsed)
            write_iops = max(0.0, (write_ops - previous[4]) / elapsed)

    return {
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
        "read_bytes_per_second": round(read_rate, 2) if read_rate is not None else None,
        "write_bytes_per_second": round(write_rate, 2) if write_rate is not None else None,
        "read_iops": round(read_iops, 2) if read_iops is not None else None,
        "write_iops": round(write_iops, 2) if write_iops is not None else None,
    }


def _load_average() -> dict[str, float | None]:
    try:
        one, five, fifteen = os.getloadavg()
        return {"1m": round(one, 3), "5m": round(five, 3), "15m": round(fifteen, 3)}
    except (AttributeError, OSError):
        return {"1m": None, "5m": None, "15m": None}


def _uptime_seconds() -> float | None:
    raw = _read_text(_PROC / "uptime").split()
    try:
        return round(float(raw[0]), 1) if raw else None
    except ValueError:
        return None


def _network_totals() -> tuple[int, int]:
    rx = tx = 0
    for line in _read_text(_PROC / "net" / "dev").splitlines()[2:]:
        if ":" not in line:
            continue
        name, raw = line.split(":", 1)
        if name.strip() == "lo":
            continue
        fields = raw.split()
        if len(fields) < 9:
            continue
        try:
            rx += int(fields[0])
            tx += int(fields[8])
        except ValueError:
            continue
    return rx, tx


def _network() -> dict[str, int | float | None]:
    global _previous_network
    now = time.monotonic()
    rx, tx = _network_totals()
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


def _temperature_c() -> float | None:
    values: list[float] = []
    roots = list((_SYS / "class" / "thermal").glob("thermal_zone*/temp"))
    roots += list((_SYS / "class" / "hwmon").glob("hwmon*/temp*_input"))
    for path in roots:
        raw = _read_text(path).strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 1000:
            value /= 1000.0
        if 0.0 < value < 150.0:
            values.append(value)
    return round(max(values), 1) if values else None


def _process_stat(pid: int) -> dict[str, Any] | None:
    raw = _read_text(_PROC / str(pid) / "stat")
    if not raw:
        return None
    right = raw.rfind(")")
    left = raw.find("(")
    if left < 0 or right < 0:
        return None
    name = raw[left + 1:right]
    fields = raw[right + 2:].split()
    try:
        # Fields after comm start at kernel field 3. utime=14, stime=15, num_threads=20, rss=24.
        ticks = int(fields[11]) + int(fields[12])
        threads = int(fields[17])
        rss_bytes = max(int(fields[21]), 0) * _PAGE_SIZE
    except (ValueError, IndexError):
        return None
    return {"pid": pid, "name": name, "ticks": ticks, "threads": threads, "rss_bytes": rss_bytes}


def _process_cpu_pct(pid: int, ticks: int, now: float) -> float | None:
    previous = _previous_process.get(pid)
    _previous_process[pid] = (now, ticks)
    if previous is None:
        return None
    elapsed = now - previous[0]
    if elapsed <= 0:
        return None
    delta_ticks = ticks - previous[1]
    if delta_ticks < 0:
        return None
    return round(max(0.0, 100.0 * (delta_ticks / _CLOCK_TICKS) / elapsed), 2)


def _processes() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now = time.monotonic()
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    own: dict[str, Any] = {"pid": os.getpid(), "cpu_usage_pct": None, "memory_rss_bytes": None, "threads": None}
    try:
        entries = list(_PROC.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        stat = _process_stat(pid)
        if stat is None:
            continue
        seen.add(pid)
        cpu_pct = _process_cpu_pct(pid, int(stat["ticks"]), now)
        row = {
            "name": stat["name"],
            "pid": pid,
            "cpu_usage_pct": cpu_pct,
            "memory_rss_bytes": stat["rss_bytes"],
            "threads": stat["threads"],
        }
        rows.append(row)
        if pid == os.getpid():
            own = dict(row)
    for pid in list(_previous_process):
        if pid not in seen:
            _previous_process.pop(pid, None)
    rows.sort(key=lambda item: float(item.get("cpu_usage_pct") or 0.0), reverse=True)
    return own, rows[:5]


def collect_host_telemetry() -> dict[str, Any]:
    """Collect one platform-neutral host telemetry sample."""
    process, top_processes = _processes()
    return {
        "schema_version": 1,
        "collected_at_unix": round(time.time(), 3),
        "host": {
            "cpu_usage_pct": _cpu_usage_pct(),
            "memory": _memory(),
            "disk": {**_disk(), **_disk_io()},
            "load_average": _load_average(),
            "uptime_seconds": _uptime_seconds(),
            "network": _network(),
            "temperature_c": _temperature_c(),
        },
        "agent": process,
        "top_processes": top_processes,
    }


__all__ = ["collect_host_telemetry"]
