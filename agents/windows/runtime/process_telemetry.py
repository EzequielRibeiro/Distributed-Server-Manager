#!/usr/bin/env python3
"""Collect a small Windows process leaderboard for observability widgets."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

_previous_processes: dict[int, tuple[str, int, int]] = {}


def _run_powershell_json(script: str, timeout: int = 10) -> Any:
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


def _raw_processes() -> list[dict[str, Any]]:
    script = r"""
$ErrorActionPreference='Stop'
$rows = @(Get-CimInstance Win32_PerfRawData_PerfProc_Process -ErrorAction Stop |
  Where-Object {
    $_.IDProcess -gt 0 -and
    $_.Name -notin @('_Total','Idle')
  } |
  ForEach-Object {
    [pscustomobject]@{
      name = [string]$_.Name
      pid = [int]$_.IDProcess
      cpu_raw = [uint64]$_.PercentProcessorTime
      timestamp_sys100ns = [uint64]$_.Timestamp_Sys100NS
      memory_rss_bytes = [int64]$_.WorkingSet
      threads = [int]$_.ThreadCount
    }
  })
@($rows) | ConvertTo-Json -Compress
"""
    payload = _run_powershell_json(script)
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def collect_top_processes(limit: int = 5) -> list[dict[str, int | float | str | None]]:
    """Return the busiest Windows processes from CPU deltas between samples.

    The raw PerfProc provider exposes cumulative process CPU time and a common
    100-ns timestamp. Deriving the delta inside the long-running Agent avoids
    the all-zero snapshots seen with the formatted provider on some Windows
    hosts/VMs. CPU is normalized by logical core count to preserve the shared
    0..100 percent dashboard contract.
    """
    global _previous_processes

    limit = max(1, min(int(limit or 5), 20))
    cores = max(1, int(os.cpu_count() or 1))
    rows = _raw_processes()
    if not rows:
        return []

    current: dict[int, tuple[str, int, int]] = {}
    result: list[dict[str, int | float | str | None]] = []

    for row in rows:
        try:
            pid = int(row.get("pid"))
            name = str(row.get("name") or "process")
            cpu_raw = int(row.get("cpu_raw"))
            timestamp = int(row.get("timestamp_sys100ns"))
        except (TypeError, ValueError):
            continue

        current[pid] = (name, cpu_raw, timestamp)
        cpu_usage: float | None = None
        previous = _previous_processes.get(pid)
        if previous is not None and previous[0] == name:
            delta_cpu = cpu_raw - previous[1]
            delta_time = timestamp - previous[2]
            if delta_cpu >= 0 and delta_time > 0:
                cpu_usage = round(
                    max(0.0, min(100.0, 100.0 * delta_cpu / delta_time / cores)),
                    2,
                )

        try:
            memory = int(row["memory_rss_bytes"]) if row.get("memory_rss_bytes") is not None else None
        except (TypeError, ValueError):
            memory = None
        try:
            threads = int(row["threads"]) if row.get("threads") is not None else None
        except (TypeError, ValueError):
            threads = None

        result.append(
            {
                "name": name,
                "pid": pid,
                "cpu_usage_pct": cpu_usage,
                "memory_rss_bytes": memory,
                "threads": threads,
            }
        )

    _previous_processes = current

    # Known CPU deltas rank first. On the first sample all values are unknown;
    # memory is then only a deterministic tie-breaker until the next heartbeat.
    result.sort(
        key=lambda item: (
            item.get("cpu_usage_pct") is not None,
            float(item.get("cpu_usage_pct") or 0.0),
            int(item.get("memory_rss_bytes") or 0),
        ),
        reverse=True,
    )
    return result[:limit]


__all__ = ["collect_top_processes"]
