#!/usr/bin/env python3
"""Stage and supervise Agent game-data commands without blocking heartbeat."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from game_data_state import JOB_ROOT, archive_job, job_paths, read_json, write_json

EXECUTOR = os.path.join(os.path.dirname(__file__), "game_data_executor.py")


def read_game_data_result() -> dict[str, Any] | None:
    if not JOB_ROOT.is_dir():
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in JOB_ROOT.glob("*.result.json"):
        value = read_json(path)
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
    request_path, result_path, log_path = job_paths(job_id)
    existing = read_json(result_path)
    if existing and str(existing.get("job_id")) == job_id:
        status = str(existing.get("status") or "").lower()
        if status in {"running", "completed", "failed"}:
            return False
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(request_path, command)
    write_json(result_path, {"job_id": job_id, "status": "running", "progress": 0})
    log_handle = open(log_path, "ab", buffering=0)
    try:
        try:
            subprocess.Popen(
                [sys.executable, EXECUTOR, str(request_path), str(result_path)],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        except Exception as exc:
            write_json(
                result_path,
                {"job_id": job_id, "status": "failed", "progress": 100, "error": str(exc)[:2000]},
            )
            raise
    finally:
        log_handle.close()
    return True


def clear_game_data_result(job_id: str) -> None:
    """Archive a final result, then remove only transient request/result files."""
    try:
        request_path, result_path, _ = job_paths(job_id)
    except ValueError:
        return
    archive_job(job_id)
    for path in (request_path, result_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = ["clear_game_data_result", "read_game_data_result", "stage_game_data_command"]
