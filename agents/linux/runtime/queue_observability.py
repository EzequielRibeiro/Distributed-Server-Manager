#!/usr/bin/env python3
"""Safe operational queue telemetry for the Agent runtime.

The queue scanner reports only counts, ages and bounded retry/status metadata. It
never emits queued payloads, paths, credentials or arbitrary error messages.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

QUEUE_PATTERNS = {
    "instance_results": "instance-results/*.json",
    "console_results": "console-results/*.json",
    "file_results": "file-results/*.json",
    "resource_results": "resource-results/*.json",
    "artifact_results": "artifact-results/*.json",
    "provisioning": "instance-provisioning/*.request.json",
    "game_data": "game-data-jobs/*.json",
    "backup_results": "backup-results/*.json",
    "broadcast_state": "broadcast-state/*.json",
    "runtime_events": "runtime-events/*.json",
}

_ALLOWED_STATUS = {
    "pending", "queued", "retrying", "running", "completed", "failed",
    "acknowledged", "unknown",
}


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _retry_count(payload: dict[str, Any]) -> int:
    for key in ("retry_count", "retries", "attempt_count", "attempts"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    return 0


def _safe_status(payload: dict[str, Any]) -> str | None:
    value = str(payload.get("status") or "").strip().lower()
    return value if value in _ALLOWED_STATUS else None


def collect_queue_observability(
    state_dir: Path,
    *,
    now: float | None = None,
    stale_after_seconds: int = 300,
) -> dict[str, dict[str, Any]]:
    """Return bounded metadata for known durable Agent queues."""
    current = time.time() if now is None else float(now)
    threshold = max(1, int(stale_after_seconds))
    result: dict[str, dict[str, Any]] = {}

    for queue_name, pattern in QUEUE_PATTERNS.items():
        files = sorted(state_dir.glob(pattern))
        oldest_age = 0
        max_retries = 0
        statuses: dict[str, int] = {}
        unreadable = 0

        for path in files:
            try:
                age = max(0, int(current - path.stat().st_mtime))
            except OSError:
                age = 0
            oldest_age = max(oldest_age, age)
            payload = _safe_json(path)
            if not payload:
                unreadable += 1
                continue
            max_retries = max(max_retries, _retry_count(payload))
            status = _safe_status(payload)
            if status:
                statuses[status] = statuses.get(status, 0) + 1

        depth = len(files)
        result[queue_name] = {
            "depth": depth,
            "oldest_age_seconds": oldest_age if depth else 0,
            "stale": bool(depth and oldest_age >= threshold),
            "stale_after_seconds": threshold,
            "max_retry_count": max_retries,
            "unreadable_items": unreadable,
            "statuses": statuses,
        }
    return result


__all__ = ["QUEUE_PATTERNS", "collect_queue_observability"]
