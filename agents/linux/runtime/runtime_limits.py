#!/usr/bin/env python3
"""Bounded operational limits for instance runtime work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeLimits:
    lock_timeout_seconds: int = 5
    provisioning_timeout_seconds: int = 3600
    start_timeout_seconds: int = 90
    stop_timeout_seconds: int = 90
    reconcile_timeout_seconds: int = 120
    max_reconcile_retries: int = 5
    max_pending_instance_commands: int = 100
    max_pending_provisioning_jobs: int = 20


def _bounded(config: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def runtime_limits(config: dict[str, Any]) -> RuntimeLimits:
    return RuntimeLimits(
        lock_timeout_seconds=_bounded(config, "runtime_lock_timeout_seconds", 5, 1, 60),
        provisioning_timeout_seconds=_bounded(config, "provisioning_timeout_seconds", 3600, 60, 86400),
        start_timeout_seconds=_bounded(config, "runtime_start_timeout_seconds", 90, 5, 600),
        stop_timeout_seconds=_bounded(config, "runtime_stop_timeout_seconds", 90, 5, 600),
        reconcile_timeout_seconds=_bounded(config, "reconcile_timeout_seconds", 120, 5, 900),
        max_reconcile_retries=_bounded(config, "reconcile_max_retries", 5, 1, 50),
        max_pending_instance_commands=_bounded(config, "max_pending_instance_commands", 100, 1, 10000),
        max_pending_provisioning_jobs=_bounded(config, "max_pending_provisioning_jobs", 20, 1, 1000),
    )


__all__ = ["RuntimeLimits", "runtime_limits"]
