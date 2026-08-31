#!/usr/bin/env python3
"""Detailed Windows operating-system inventory for Controller display."""
from __future__ import annotations

import json
import os
import platform
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


def collect_system_inventory() -> dict[str, str | None]:
    script = r"""
$ErrorActionPreference='Stop'
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop | Select-Object -First 1
$displayVersion = $null
$edition = $null
try {
  $cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop
  $displayVersion = [string]$cv.DisplayVersion
  $edition = [string]$cv.EditionID
} catch {}
@{
  name = [string]$os.Caption
  version = [string]$os.Version
  build = [string]$os.BuildNumber
  architecture = [string]$os.OSArchitecture
  display_version = $displayVersion
  edition = $edition
} | ConvertTo-Json -Compress
"""
    payload = _run_powershell_json(script)
    fallback_arch = platform.machine() or os.environ.get("PROCESSOR_ARCHITECTURE")
    if not isinstance(payload, dict):
        return {
            "family": "windows",
            "name": "Windows",
            "pretty_name": "Windows",
            "version": platform.version() or None,
            "build": platform.version().split(".")[-1] if platform.version() else None,
            "display_version": None,
            "edition": None,
            "kernel": None,
            "architecture": fallback_arch,
        }

    name = str(payload.get("name") or "Windows").strip()
    return {
        "family": "windows",
        "name": name,
        "pretty_name": name,
        "version": str(payload.get("version") or "").strip() or None,
        "build": str(payload.get("build") or "").strip() or None,
        "display_version": str(payload.get("display_version") or "").strip() or None,
        "edition": str(payload.get("edition") or "").strip() or None,
        "kernel": None,
        "architecture": str(payload.get("architecture") or fallback_arch or "").strip() or None,
    }


__all__ = ["collect_system_inventory"]
