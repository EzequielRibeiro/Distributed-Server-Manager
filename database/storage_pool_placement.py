#!/usr/bin/env python3
"""Controller-side Storage Pool selection from Agent heartbeat inventory."""
from __future__ import annotations

import json
from typing import Any


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def storage_pools_from_metadata(metadata_json: Any) -> list[dict[str, Any]]:
    metadata = _mapping(metadata_json)
    telemetry = metadata.get("telemetry") if isinstance(metadata.get("telemetry"), dict) else {}
    pools = telemetry.get("storage_pools")
    return [dict(item) for item in pools if isinstance(item, dict)] if isinstance(pools, list) else []


def _number(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_pool(item: dict[str, Any]) -> dict[str, Any] | None:
    pool_id = str(item.get("id") or "").strip()
    if not pool_id:
        return None
    return {
        "storage_pool_id": pool_id,
        "storage_class": str(item.get("storage_class") or "standard").strip().lower() or "standard",
        "enabled": bool(item.get("enabled", True)),
        "default": bool(item.get("default", False)),
        "health": str(item.get("health") or "unknown").strip().lower() or "unknown",
        "priority": _number(item.get("priority"), 0),
        "usable_bytes": max(0, _number(item.get("usable_bytes"), 0)),
        "free_bytes": max(0, _number(item.get("free_bytes"), 0)),
        "reserve_bytes": max(0, _number(item.get("reserve_bytes"), 0)),
        "root_path": str(item.get("root_path") or "").strip() or None,
    }


def select_storage_pool(
    metadata_json: Any,
    *,
    requested_pool_id: str | None = None,
    preferred_storage_class: str | None = None,
    required_bytes: int | None = None,
) -> dict[str, Any] | None:
    """Return a deterministic pool decision, or None for legacy single-root Agents.

    Explicit pool requests are strict: a missing, disabled, unhealthy or undersized
    pool is rejected rather than silently replaced. Automatic selection filters
    unavailable pools, applies class/capacity requirements, then ranks by priority,
    usable capacity, default-pool preference and stable ID.
    """
    raw_pools = storage_pools_from_metadata(metadata_json)
    if not raw_pools:
        return None
    pools = [pool for item in raw_pools if (pool := _normalized_pool(item)) is not None]
    if not pools:
        return None

    requested = str(requested_pool_id or "").strip() or None
    preferred_class = str(preferred_storage_class or "").strip().lower() or None
    minimum = max(0, _number(required_bytes, 0)) if required_bytes is not None else 0

    def eligible(pool: dict[str, Any]) -> bool:
        if not pool["enabled"] or pool["health"] != "online":
            return False
        if minimum and pool["usable_bytes"] < minimum:
            return False
        return True

    if requested:
        match = next((pool for pool in pools if pool["storage_pool_id"] == requested), None)
        if match is None:
            raise ValueError(f"requested storage pool not found: {requested}")
        if not eligible(match):
            raise ValueError(f"requested storage pool is not eligible: {requested}")
        if preferred_class and match["storage_class"] != preferred_class:
            raise ValueError(f"requested storage pool does not match storage class: {preferred_class}")
        return {**match, "source": "explicit", "reason": "requested_pool"}

    candidates = [pool for pool in pools if eligible(pool)]
    if preferred_class:
        candidates = [pool for pool in candidates if pool["storage_class"] == preferred_class]
    if not candidates:
        detail = " for requested storage class" if preferred_class else ""
        raise ValueError(f"no eligible storage pool{detail}")

    candidates.sort(
        key=lambda pool: (
            -pool["priority"],
            -pool["usable_bytes"],
            -int(pool["default"]),
            pool["storage_pool_id"],
        )
    )
    selected = candidates[0]
    reason = "priority_capacity"
    if preferred_class:
        reason = "storage_class_priority_capacity"
    return {**selected, "source": "telemetry", "reason": reason}


__all__ = ["select_storage_pool", "storage_pools_from_metadata"]
