#!/usr/bin/env python3
"""Read-only health contract for required Controller systemd services."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

REQUIRED_CONTROLLER_SERVICES = (
    "dsm-controller-service-topology.service",
    "dsm-controller-log-reader.service",
    "dsm-dashboard-worker.service",
    "dsm-alert-engine.service",
    "dsm-dashboard.service",
)


def _systemd_available() -> bool:
    return Path("/run/systemd/system").is_dir() and shutil.which("systemctl") is not None


def controller_service_health() -> dict[str, Any]:
    """Return secret-free required-service health without changing systemd state."""
    if not _systemd_available():
        return {
            "checked": False,
            "ready": True,
            "required": list(REQUIRED_CONTROLLER_SERVICES),
            "inactive": [],
            "states": {},
            "reason": "systemd_unavailable",
        }

    states: dict[str, str] = {}
    inactive: list[str] = []
    for unit in REQUIRED_CONTROLLER_SERVICES:
        completed = subprocess.run(
            ["systemctl", "is-active", unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        state = (completed.stdout or completed.stderr or "unknown").strip().lower() or "unknown"
        states[unit] = state
        if completed.returncode != 0 or state != "active":
            inactive.append(unit)

    return {
        "checked": True,
        "ready": not inactive,
        "required": list(REQUIRED_CONTROLLER_SERVICES),
        "inactive": inactive,
        "states": states,
        "reason": None if not inactive else "required_controller_service_inactive",
    }


__all__ = ["REQUIRED_CONTROLLER_SERVICES", "controller_service_health"]
