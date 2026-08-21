#!/usr/bin/env python3
"""Atomic Agent-local state for B10 provisioning jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
PROVISION_ROOT = STATE_DIR / "instance-provisioning"
HISTORY_ROOT = PROVISION_ROOT / "history"


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > 191 or any(ch not in allowed for ch in text):
        raise ValueError("invalid provisioning_id")
    return text


def paths(provisioning_id: str) -> tuple[Path, Path, Path]:
    token = _safe_id(provisioning_id)
    return (
        PROVISION_ROOT / f"{token}.request.json",
        PROVISION_ROOT / f"{token}.result.json",
        PROVISION_ROOT / f"{token}.log",
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


def archive(provisioning_id: str) -> None:
    request_path, result_path, log_path = paths(provisioning_id)
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    for source in (request_path, result_path, log_path):
        if not source.exists():
            continue
        destination = HISTORY_ROOT / source.name
        try:
            os.replace(source, destination)
        except OSError:
            pass


__all__ = ["HISTORY_ROOT", "PROVISION_ROOT", "archive", "paths", "read_json", "write_json"]
