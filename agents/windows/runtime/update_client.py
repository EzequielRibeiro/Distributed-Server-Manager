#!/usr/bin/env python3
"""Stage and launch Windows Agent updates from the shared heartbeat protocol."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
REQUEST_PATH = STATE_DIR / "update-request.json"
RESULT_PATH = STATE_DIR / "update-result.json"


def stage_update_request(command: dict[str, Any]) -> bool:
    version = str(command.get("desired_version", "")).strip()
    channel = str(command.get("channel", "stable")).strip().lower()
    if not version or channel not in {"stable", "beta", "local/manual"}:
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = None
    try:
        existing = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if isinstance(existing, dict) and existing.get("desired_version") == version:
        return False
    temp = REQUEST_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(command, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(REQUEST_PATH)
    updater = Path(__file__).resolve().parents[1] / "updater" / "updater.py"
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([sys.executable, str(updater)], creationflags=flags, close_fds=True)
    return True


def read_update_result() -> dict[str, Any] | None:
    try:
        value = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def clear_update_result() -> None:
    try:
        RESULT_PATH.unlink()
    except FileNotFoundError:
        pass


__all__ = ["stage_update_request", "read_update_result", "clear_update_result"]
