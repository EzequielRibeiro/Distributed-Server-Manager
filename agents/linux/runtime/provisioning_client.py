#!/usr/bin/env python3
"""Stage and supervise B10 provisioning without blocking Agent heartbeat."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from provisioning_state import PROVISION_ROOT, archive, paths, read_json, write_json

EXECUTOR = os.path.join(os.path.dirname(__file__), "provisioning_executor.py")


def read_provisioning_result() -> dict[str, Any] | None:
    if not PROVISION_ROOT.is_dir():
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in PROVISION_ROOT.glob("*.result.json"):
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


def stage_provisioning_command(command: dict[str, Any] | None, *, config_path: Path) -> bool:
    if not isinstance(command, dict):
        return False
    provisioning_id = str(command.get("provisioning_id") or "").strip()
    instance_id = str(command.get("instance_id") or "").strip()
    if not provisioning_id or not instance_id:
        return False
    request_path, result_path, log_path = paths(provisioning_id)
    existing = read_json(result_path)
    if existing and str(existing.get("provisioning_id") or "") == provisioning_id:
        if str(existing.get("status") or "").lower() in {"running", "completed", "failed"}:
            return False
    PROVISION_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(request_path, command)
    write_json(
        result_path,
        {
            "provisioning_id": provisioning_id,
            "instance_id": instance_id,
            "status": "running",
            "current_step": "staged",
            "progress": 1,
        },
    )
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
            write_json(
                result_path,
                {
                    "provisioning_id": provisioning_id,
                    "instance_id": instance_id,
                    "status": "failed",
                    "current_step": "stage",
                    "progress": 100,
                    "error": str(exc)[:2000],
                },
            )
            raise
    finally:
        log_handle.close()
    return True


def clear_provisioning_result(provisioning_id: str) -> None:
    try:
        request_path, result_path, _ = paths(provisioning_id)
    except ValueError:
        return
    archive(provisioning_id)
    for path in (request_path, result_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = ["clear_provisioning_result", "read_provisioning_result", "stage_provisioning_command"]
