#!/usr/bin/env python3
"""Agent-owned storage pool policy for private per-instance state."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

DEFAULT_INSTANCE_STORAGE_ROOT = Path("/var/lib/capivara-instances")
DEFAULT_STORAGE_POOL_ID = "default"
_POOL_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STORAGE_CLASS = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FORBIDDEN_ROOTS = tuple(Path(value) for value in ("/boot", "/dev", "/etc", "/proc", "/root", "/run", "/sys", "/usr"))


def _root(value: Any, label: str = "storage pool root") -> Path:
    raw = str(value or "").strip()
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"):
        raise ValueError(f"{label} cannot be filesystem root")
    for forbidden in _FORBIDDEN_ROOTS:
        try:
            resolved.relative_to(forbidden)
        except ValueError:
            continue
        raise ValueError(f"{label} is inside a protected system path")
    return resolved


def _pool_id(value: Any) -> str:
    token = str(value or "").strip()
    if not _POOL_ID.fullmatch(token):
        raise ValueError("invalid storage_pool_id")
    return token


def _storage_class(value: Any) -> str:
    token = str(value or "standard").strip().lower()
    if not _STORAGE_CLASS.fullmatch(token):
        raise ValueError("invalid storage_class")
    return token


def _normalize_pool(raw: dict[str, Any]) -> dict[str, Any]:
    pool_id = _pool_id(raw.get("id") or raw.get("storage_pool_id"))
    root = _root(raw.get("root_path") or raw.get("root"), f"storage pool {pool_id} root")
    reserve = int(raw.get("reserve_bytes") or 0)
    priority = int(raw.get("priority") or 0)
    if reserve < 0:
        raise ValueError("storage pool reserve_bytes cannot be negative")
    return {
        "id": pool_id,
        "name": str(raw.get("name") or pool_id).strip()[:160] or pool_id,
        "root_path": str(root),
        "storage_class": _storage_class(raw.get("storage_class")),
        "enabled": bool(raw.get("enabled", True)),
        "priority": priority,
        "reserve_bytes": reserve,
    }


def storage_pools(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized pools, synthesizing the legacy single-root contract when absent."""
    raw_pools = config.get("storage_pools") if isinstance(config, dict) else None
    if not isinstance(raw_pools, list) or not raw_pools:
        root = _root(
            (config or {}).get("instance_storage_root") or DEFAULT_INSTANCE_STORAGE_ROOT,
            "Agent instance_storage_root",
        )
        return [{
            "id": DEFAULT_STORAGE_POOL_ID,
            "name": "Default",
            "root_path": str(root),
            "storage_class": "standard",
            "enabled": True,
            "priority": 0,
            "reserve_bytes": 0,
            "legacy": True,
        }]

    pools: list[dict[str, Any]] = []
    ids: set[str] = set()
    roots: set[str] = set()
    for item in raw_pools:
        if not isinstance(item, dict):
            raise ValueError("storage_pools entries must be objects")
        pool = _normalize_pool(item)
        if pool["id"] in ids:
            raise ValueError(f"duplicate storage pool id: {pool['id']}")
        if pool["root_path"] in roots:
            raise ValueError(f"duplicate storage pool root: {pool['root_path']}")
        ids.add(pool["id"])
        roots.add(pool["root_path"])
        pools.append(pool)
    return pools


def default_storage_pool_id(config: dict[str, Any]) -> str:
    pools = storage_pools(config)
    if len(pools) == 1 and pools[0].get("legacy"):
        return DEFAULT_STORAGE_POOL_ID
    requested = str((config or {}).get("default_storage_pool_id") or "").strip()
    if not requested:
        enabled = [pool for pool in pools if pool["enabled"]]
        if len(enabled) == 1:
            return str(enabled[0]["id"])
        raise ValueError("default_storage_pool_id is required when multiple storage pools are configured")
    requested = _pool_id(requested)
    if requested not in {pool["id"] for pool in pools}:
        raise ValueError("default_storage_pool_id does not exist")
    return requested


def resolve_storage_pool(config: dict[str, Any], pool_id: str | None = None, *, require_enabled: bool = True) -> dict[str, Any]:
    selected = _pool_id(pool_id) if pool_id else default_storage_pool_id(config)
    for pool in storage_pools(config):
        if pool["id"] != selected:
            continue
        if require_enabled and not pool["enabled"]:
            raise ValueError(f"storage pool is disabled: {selected}")
        return dict(pool)
    raise ValueError(f"storage pool not found: {selected}")


def instance_storage_root(config: dict[str, Any], pool_id: str | None = None) -> Path:
    return Path(resolve_storage_pool(config, pool_id)["root_path"])


def pool_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Report capacity without creating or modifying storage paths."""
    result: list[dict[str, Any]] = []
    default_id = default_storage_pool_id(config)
    for pool in storage_pools(config):
        item = dict(pool)
        item["default"] = pool["id"] == default_id
        root = Path(pool["root_path"])
        try:
            usage = shutil.disk_usage(root)
        except OSError as exc:
            item.update({"health": "unavailable", "error": str(exc)[:500], "total_bytes": None, "free_bytes": None, "usable_bytes": None})
        else:
            usable = max(0, int(usage.free) - int(pool["reserve_bytes"]))
            item.update({"health": "online", "total_bytes": int(usage.total), "free_bytes": int(usage.free), "usable_bytes": usable})
        result.append(item)
    return result


__all__ = [
    "DEFAULT_INSTANCE_STORAGE_ROOT",
    "DEFAULT_STORAGE_POOL_ID",
    "default_storage_pool_id",
    "instance_storage_root",
    "pool_inventory",
    "resolve_storage_pool",
    "storage_pools",
]
