#!/usr/bin/env python3
"""Stage and supervise per-instance Storage Pool migration without blocking heartbeat."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from storage_pool_migration_state import MIGRATION_ROOT, archive, paths, read_json, write_json

EXECUTOR = os.path.join(os.path.dirname(__file__), "storage_pool_migration_executor.py")


def read_storage_pool_migration_result() -> dict[str, Any] | None:
    if not MIGRATION_ROOT.is_dir():
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in MIGRATION_ROOT.glob("*.result.json"):
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


def stage_storage_pool_migration(command: dict[str, Any] | None, *, config_path: Path) -> bool:
    if not isinstance(command, dict):
        return False
    migration_id = str(command.get("migration_id") or "").strip()
    instance_id = str(command.get("instance_id") or "").strip()
    if not migration_id or not instance_id:
        return False
    request_path, result_path, log_path = paths(migration_id)
    existing = read_json(result_path)
    if existing and str(existing.get("migration_id") or "") == migration_id:
        if str(existing.get("status") or "").lower() in {"running", "completed", "failed"}:
            return False
    MIGRATION_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(request_path, command)
    write_json(result_path, {
        "migration_id": migration_id,
        "instance_id": instance_id,
        "status": "running",
        "current_step": "staged",
        "progress": 1,
    })
    log_handle = open(log_path, "ab", buffering=0)
    try:
        try:
            subprocess.Popen(
                [sys.executable, EXECUTOR, str(config_path), str(request_path), str(result_path)],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        except Exception as exc:
            write_json(result_path, {
                "migration_id": migration_id,
                "instance_id": instance_id,
                "status": "failed",
                "current_step": "stage",
                "progress": 100,
                "error": str(exc)[:2000],
            })
            raise
    finally:
        log_handle.close()
    return True


def clear_storage_pool_migration_result(migration_id: str) -> None:
    try:
        request_path, result_path, _ = paths(migration_id)
    except ValueError:
        return
    archive(migration_id)
    for path in (request_path, result_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "clear_storage_pool_migration_result",
    "read_storage_pool_migration_result",
    "stage_storage_pool_migration",
]
