#!/usr/bin/env python3
"""Canonical defaults for Customer Workspace instance backup scheduling."""

from __future__ import annotations

from typing import Any


DEFAULT_ENABLED = True
DEFAULT_SCHEDULE_TIME = "04:00"
DEFAULT_SCHEDULE_TIMEZONE = "UTC"
DEFAULT_HEALTHY_ONLY = True
DEFAULT_KEEP_SINGLE_OPERATIONAL = True


def default_instance_backup_policy(instance_id: str) -> dict[str, Any]:
    """Return a fresh default Workspace backup policy."""
    return {
        "instance_id": str(instance_id),
        "enabled": DEFAULT_ENABLED,
        "schedule_time": DEFAULT_SCHEDULE_TIME,
        "schedule_timezone": DEFAULT_SCHEDULE_TIMEZONE,
        "healthy_only": DEFAULT_HEALTHY_ONLY,
        "keep_single_operational": DEFAULT_KEEP_SINGLE_OPERATIONAL,
    }


__all__ = [
    "DEFAULT_ENABLED",
    "DEFAULT_SCHEDULE_TIME",
    "DEFAULT_SCHEDULE_TIMEZONE",
    "DEFAULT_HEALTHY_ONLY",
    "DEFAULT_KEEP_SINGLE_OPERATIONAL",
    "default_instance_backup_policy",
]
