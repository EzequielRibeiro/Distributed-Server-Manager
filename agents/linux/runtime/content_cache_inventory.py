#!/usr/bin/env python3
"""Local observability for Agent-scoped managed-content provider caches."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

def _state_root() -> Path:
    return Path(
        os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent")
    )


def _stats_path() -> Path:
    return _state_root() / "content-cache-stats.json"


def _lock_path() -> Path:
    return _state_root() / "content-cache-stats.lock"


def _workshop_root() -> Path:
    return _state_root() / "provider-cache" / "steam-workshop"


def _empty_stats() -> dict[str, int]:
    return {"hits": 0, "misses": 0, "downloads": 0}


def _read_stats() -> dict[str, int]:
    try:
        value = json.loads(_stats_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_stats()
    result = _empty_stats()
    for key in result:
        try:
            result[key] = max(0, int(value.get(key, 0)))
        except (AttributeError, TypeError, ValueError):
            result[key] = 0
    return result


def record_cache_event(event: str) -> dict[str, int]:
    key = str(event or "").strip().lower()
    if key not in {"hit", "miss", "download"}:
        raise ValueError("invalid content cache event")
    try:
        root = _state_root()
        stats_path = _stats_path()
        lock_path = _lock_path()
        root.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                stats = _read_stats()
                field = {"hit": "hits", "miss": "misses", "download": "downloads"}[key]
                stats[field] += 1
                temp = stats_path.with_suffix(".tmp")
                temp.write_text(
                    json.dumps(stats, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                os.chmod(temp, 0o600)
                os.replace(temp, stats_path)
                os.chmod(stats_path, 0o600)
                return dict(stats)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except OSError:
        return _read_stats()


def _tree_size(path: Path) -> int:
    total = 0
    try:
        entries = list(path.rglob("*"))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def snapshot() -> dict[str, Any]:
    stats = _read_stats()
    items = 0
    revisions = 0
    bytes_used = 0
    workshop_root = _workshop_root()
    if workshop_root.is_dir():
        for app in workshop_root.iterdir():
            if not app.is_dir():
                continue
            for item in app.iterdir():
                revisions_root = item / "revisions"
                if not revisions_root.is_dir():
                    continue
                item_revisions = [
                    path
                    for path in revisions_root.iterdir()
                    if path.is_dir() and path.name.isdigit()
                ]
                if not item_revisions:
                    continue
                items += 1
                revisions += len(item_revisions)
                bytes_used += sum(_tree_size(path) for path in item_revisions)
    return {
        "schema_version": 1,
        "kind": "ContentCacheInventory",
        "provider": "steam-workshop",
        **stats,
        "avoided_downloads": stats["hits"],
        "items": items,
        "revisions": revisions,
        "bytes": bytes_used,
    }


__all__ = ["record_cache_event", "snapshot"]
