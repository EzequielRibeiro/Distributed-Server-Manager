#!/usr/bin/env python3
"""Detailed Linux operating-system inventory for Controller display."""
from __future__ import annotations

import platform
from pathlib import Path


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        values[key] = raw.strip().strip('"').strip("'")
    return values


def collect_system_inventory() -> dict[str, str | None]:
    release = _os_release()
    name = release.get("NAME") or platform.system() or "Linux"
    pretty = release.get("PRETTY_NAME") or name
    return {
        "family": "linux",
        "name": name,
        "pretty_name": pretty,
        "version": release.get("VERSION_ID") or platform.release() or None,
        "build": None,
        "display_version": release.get("VERSION") or None,
        "edition": None,
        "kernel": platform.release() or None,
        "architecture": platform.machine() or None,
    }


__all__ = ["collect_system_inventory"]
