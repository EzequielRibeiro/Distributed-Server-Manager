#!/usr/bin/env python3
"""Stage and supervise Agent game-data commands without blocking heartbeat."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
JOB_ROOT = STATE_ROOT / "game-data-jobs"
EXECUTOR = Path(__file__).resolve().parent / "game_data_executor.py"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def _paths(job_id: str) -> tuple[Path, Path, Path]:
    safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
    if not safe or safe != str(job_id):
        raise ValueError("invalid game-data job id")
    return (
        JOB_ROOT / f"{safe}.request.json",
        JOB_ROOT / f"{safe}.result.json",
        JOB_ROOT / f"{safe}.log",
    )


def read_game_data_result() -> dict[str, Any] | None:
    if not JOB_ROOT.is_dir():
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in JOB_ROOT.glob("*.result.json"):
        value = _read_json(path)
        if not value:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        candidates.append((modified, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def stage_game_data_command(command: dict[str, Any] | None) -> bool:
    if not isinstance(command, dict):
        return False
    job_id = str(command.get("job_id") or "").strip()
    selection = command.get("selection")
    if not job_id or not isinstance(selection, dict):
        return False

    request_path, result_path, log_path = _paths(job_id)
    existing = _read_json(result_path)
    if existing and str(existing.get("job_id")) == job_id:
        status = str(existing.get("status") or "").lower()
        if status in {"running", "completed", "failed"}:
            return False

    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(request_path, command)
    log_handle = open(log_path, "ab", buffering=0)
    try:
        subprocess.Popen(
            [sys.executable, str(EXECUTOR), str(request_path), str(result_path)],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    return True


def clear_game_data_result(job_id: str) -> None:
    try:
        request_path, result_path, _ = _paths(job_id)
    except ValueError:
        return
    for path in (request_path, result_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = ["clear_game_data_result", "read_game_data_result", "stage_game_data_command"]
