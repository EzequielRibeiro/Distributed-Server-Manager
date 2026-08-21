#!/usr/bin/env python3
"""Consume Controller game-data jobs for the local Agent in Hybrid mode."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from agent_game_data_repository import AgentGameDataRepository


def _job_root(root: Path) -> Path:
    return root / "runtime" / "hybrid-game-data-jobs"


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


def _paths(root: Path, job_id: str) -> tuple[Path, Path, Path]:
    safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
    if not safe or safe != str(job_id):
        raise ValueError("invalid game-data job id")
    base = _job_root(root)
    return base / f"{safe}.request.json", base / f"{safe}.result.json", base / f"{safe}.log"


def _latest_result(root: Path) -> dict[str, Any] | None:
    base = _job_root(root)
    if not base.is_dir():
        return None
    items: list[tuple[float, dict[str, Any]]] = []
    for path in base.glob("*.result.json"):
        value = _read_json(path)
        if not value:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        items.append((modified, value))
    if not items:
        return None
    items.sort(key=lambda item: item[0], reverse=True)
    return items[0][1]


def _stage(root: Path, command: dict[str, Any]) -> bool:
    job_id = str(command.get("job_id") or "").strip()
    if not job_id or not isinstance(command.get("selection"), dict):
        return False
    request_path, result_path, log_path = _paths(root, job_id)
    existing = _read_json(result_path)
    if existing and str(existing.get("status") or "").lower() in {"running", "completed", "failed"}:
        return False
    _write_json(request_path, command)
    executor = root / "dashboard" / "workers" / "hybrid_game_data_executor.py"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "ab", buffering=0)
    try:
        subprocess.Popen(
            [sys.executable, str(executor), str(root), str(request_path), str(result_path)],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
            env={**os.environ, "DSM_ROOT": str(root)},
        )
    finally:
        log_handle.close()
    return True


def process_hybrid_game_data_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    repository = AgentGameDataRepository(backend)
    repository.initialize()
    reported = _latest_result(root)
    state = repository.apply_result(agent_id, reported) if reported else None
    command = repository.command_for_agent(agent_id)
    staged = False
    if command:
        state = repository.mark_delivered(str(command["job_id"]))
        staged = _stage(root, command)
    return {"state": state or {"status": "idle"}, "command": command, "staged": staged}


__all__ = ["process_hybrid_game_data_cycle"]
