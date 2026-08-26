#!/usr/bin/env python3
"""Atomic Agent-local state for per-instance Storage Pool migration jobs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
MIGRATION_ROOT = STATE_DIR / "storage-pool-migrations"
HISTORY_ROOT = MIGRATION_ROOT / "history"


def safe_id(value: Any, label: str = "migration_id") -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > 191 or any(ch not in allowed for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def paths(migration_id: str) -> tuple[Path, Path, Path]:
    token = safe_id(migration_id)
    return (
        MIGRATION_ROOT / f"{token}.request.json",
        MIGRATION_ROOT / f"{token}.result.json",
        MIGRATION_ROOT / f"{token}.log",
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def archive(migration_id: str) -> None:
    request_path, result_path, log_path = paths(migration_id)
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    for source in (request_path, result_path, log_path):
        if not source.exists():
            continue
        try:
            os.replace(source, HISTORY_ROOT / source.name)
        except OSError:
            pass


__all__ = ["HISTORY_ROOT", "MIGRATION_ROOT", "archive", "paths", "read_json", "safe_id", "write_json"]
