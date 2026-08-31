#!/usr/bin/env python3
"""Collect a small Windows process leaderboard for observability widgets."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any


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


def collect_top_processes(limit: int = 5) -> list[dict[str, int | float | str | None]]:
    """Return the busiest Windows processes by instantaneous CPU percentage.

    PercentProcessorTime from the formatted PerfProc provider is normalized by
    logical CPU count so the platform-neutral widget keeps a 0..100 percent
    interpretation. Kernel pseudo-processes and invalid PIDs are excluded.
    """
    limit = max(1, min(int(limit or 5), 20))
    cores = max(1, int(os.cpu_count() or 1))
    script = rf"""
$ErrorActionPreference='Stop'
$cores={cores}
$limit={limit}
$rows = @(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -ErrorAction Stop |
  Where-Object {{
    $_.IDProcess -gt 0 -and
    $_.Name -notin @('_Total','Idle')
  }} |
  ForEach-Object {{
    [pscustomobject]@{{
      name = [string]$_.Name
      pid = [int]$_.IDProcess
      cpu_usage_pct = [math]::Min(100.0, ([double]$_.PercentProcessorTime / [math]::Max(1,$cores)))
      memory_rss_bytes = [int64]$_.WorkingSet
      threads = [int]$_.ThreadCount
    }}
  }} |
  Sort-Object cpu_usage_pct -Descending |
  Select-Object -First $limit)
@($rows) | ConvertTo-Json -Compress
"""
    payload = _run_powershell_json(script)
    if not isinstance(payload, list):
        return []
    result: list[dict[str, int | float | str | None]] = []
    for row in payload[:limit]:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("pid"))
        except (TypeError, ValueError):
            continue
        result.append(
            {
                "name": str(row.get("name") or "process"),
                "pid": pid,
                "cpu_usage_pct": round(float(row.get("cpu_usage_pct") or 0.0), 2),
                "memory_rss_bytes": int(row["memory_rss_bytes"]) if row.get("memory_rss_bytes") is not None else None,
                "threads": int(row["threads"]) if row.get("threads") is not None else None,
            }
        )
    return result


__all__ = ["collect_top_processes"]
