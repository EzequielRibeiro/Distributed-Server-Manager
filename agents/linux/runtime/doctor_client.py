#!/usr/bin/env python3
"""Execute the fixed local Agent Doctor contract on Controller request."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from local_cli import _doctor

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RESULT_PATH = STATE_DIR / "doctor-result.json"


def _write(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = RESULT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(RESULT_PATH)
    os.chmod(RESULT_PATH, 0o600)


def handle_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    request_id = str(command.get("request_id") or "").strip()
    if not request_id:
        raise ValueError("doctor request_id is required")
    current = read_result()
    if current and str(current.get("request_id")) == request_id:
        return current
    try:
        report = _doctor(config)
        payload = {
            "request_id": request_id,
            "status": "completed",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "result": report,
        }
    except Exception as exc:
        payload = {
            "request_id": request_id,
            "status": "failed",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": str(exc)[:2000],
        }
    _write(payload)
    return payload


def read_result() -> dict[str, Any] | None:
    try:
        payload = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_result(request_id: str | None = None) -> None:
    current = read_result()
    if request_id and current and str(current.get("request_id")) != str(request_id):
        return
    try:
        RESULT_PATH.unlink()
    except FileNotFoundError:
        pass
