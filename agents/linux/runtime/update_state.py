#!/usr/bin/env python3
"""Read-only helpers for Linux Agent update status/history."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"
HISTORY_DIR = STATE_DIR / "update-history"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def status() -> dict[str, Any]:
    return {
        "pending": _read_json(REQUEST_PATH),
        "last_result": _read_json(RESULT_PATH),
    }


def history(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    try:
        files = sorted(HISTORY_DIR.glob("*.json"), key=lambda item: item.name, reverse=True)
    except OSError:
        files = []
    values: list[dict[str, Any]] = []
    for path in files:
        payload = _read_json(path)
        if payload is not None:
            values.append(payload)
        if len(values) >= limit:
            break
    return values


__all__ = ["status", "history"]
