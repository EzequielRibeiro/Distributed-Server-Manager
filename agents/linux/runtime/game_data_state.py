#!/usr/bin/env python3
"""Local persistent game-data inventory and job history for Linux Agent."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_ROOT = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
GAME_DATA_ROOT = Path(os.environ.get("CAPIVARA_AGENT_GAME_DATA_ROOT", str(STATE_ROOT / "game-data"))).resolve()
JOB_ROOT = STATE_ROOT / "game-data-jobs"
HISTORY_ROOT = JOB_ROOT / "history"
GAME_STATE_ROOT = STATE_ROOT / "game-data-state"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or any(ch not in allowed for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def job_paths(job_id: str) -> tuple[Path, Path, Path]:
    safe = _safe_token(job_id, "game-data job id")
    return (
        JOB_ROOT / f"{safe}.request.json",
        JOB_ROOT / f"{safe}.result.json",
        JOB_ROOT / f"{safe}.log",
    )


def archive_job(job_id: str) -> dict[str, Any] | None:
    """Persist a sanitized final job summary before transient files are removed."""
    request_path, result_path, log_path = job_paths(job_id)
    request = read_json(request_path) or {}
    result = read_json(result_path) or {}
    status = str(result.get("status") or "").strip().lower()
    if status not in {"completed", "failed"}:
        return None
    selection = request.get("selection") if isinstance(request.get("selection"), dict) else {}
    summary = {
        "job_id": job_id,
        "action": request.get("action"),
        "environment_id": request.get("environment_id"),
        "selector": request.get("selector"),
        "status": status,
        "progress": result.get("progress"),
        "error": result.get("error"),
        "provider": result.get("provider") or selection.get("provider"),
        "game": result.get("game") or selection.get("game"),
        "version": result.get("version") or selection.get("version"),
        "target_path": result.get("target_path"),
        "log_path": str(log_path),
        "archived_at": _now(),
    }
    history_path = HISTORY_ROOT / f"{_safe_token(job_id, 'game-data job id')}.json"
    write_json(history_path, {key: value for key, value in summary.items() if value is not None})
    return summary


def _transient_job(job_id: str) -> dict[str, Any] | None:
    request_path, result_path, log_path = job_paths(job_id)
    request = read_json(request_path) or {}
    result = read_json(result_path) or {}
    if not request and not result:
        return None
    selection = request.get("selection") if isinstance(request.get("selection"), dict) else {}
    status = str(result.get("status") or "queued").strip().lower() or "queued"
    return {
        "job_id": job_id,
        "action": request.get("action"),
        "environment_id": request.get("environment_id"),
        "selector": request.get("selector"),
        "status": status,
        "progress": result.get("progress", 0),
        "error": result.get("error"),
        "provider": result.get("provider") or selection.get("provider"),
        "game": result.get("game") or selection.get("game"),
        "version": result.get("version") or selection.get("version"),
        "target_path": result.get("target_path"),
        "log_path": str(log_path),
        "active": status not in {"completed", "failed"},
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    safe = _safe_token(job_id, "game-data job id")
    transient = _transient_job(safe)
    if transient:
        return transient
    history = read_json(HISTORY_ROOT / f"{safe}.json")
    if history:
        return {**history, "active": False}
    return None


def list_jobs(*, active_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    items: list[tuple[float, dict[str, Any]]] = []
    if JOB_ROOT.is_dir():
        ids = {path.name[: -len(".request.json")] for path in JOB_ROOT.glob("*.request.json")}
        ids.update(path.name[: -len(".result.json")] for path in JOB_ROOT.glob("*.result.json"))
        for job_id in ids:
            payload = _transient_job(job_id)
            if not payload or (active_only and not payload.get("active")):
                continue
            try:
                stamp = max(
                    (JOB_ROOT / f"{job_id}.request.json").stat().st_mtime if (JOB_ROOT / f"{job_id}.request.json").exists() else 0,
                    (JOB_ROOT / f"{job_id}.result.json").stat().st_mtime if (JOB_ROOT / f"{job_id}.result.json").exists() else 0,
                )
            except OSError:
                stamp = 0.0
            items.append((stamp, payload))
    if not active_only and HISTORY_ROOT.is_dir():
        for path in HISTORY_ROOT.glob("*.json"):
            payload = read_json(path)
            if not payload:
                continue
            try:
                stamp = path.stat().st_mtime
            except OSError:
                stamp = 0.0
            items.append((stamp, {**payload, "active": False}))
    items.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in items[:limit]]


def record_game_data(*, job_id: str, action: str, selection: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    game = _safe_token(result.get("game") or selection.get("game"), "game id")
    state = {
        "game": game,
        "installed": True,
        "provider": result.get("provider") or selection.get("provider"),
        "version": result.get("version") or selection.get("version"),
        "target_path": result.get("target_path"),
        "last_action": action,
        "last_job_id": job_id,
        "updated_at": _now(),
    }
    write_json(GAME_STATE_ROOT / f"{game}.json", {key: value for key, value in state.items() if value is not None})
    return state


def list_game_data() -> list[dict[str, Any]]:
    if not GAME_STATE_ROOT.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(GAME_STATE_ROOT.glob("*.json")):
        payload = read_json(path)
        if payload:
            items.append(payload)
    return items


def get_game_data(game: str) -> dict[str, Any] | None:
    safe = _safe_token(game, "game id")
    payload = read_json(GAME_STATE_ROOT / f"{safe}.json")
    if not payload:
        return None
    target = str(payload.get("target_path") or "").strip()
    if target:
        path = Path(target)
        try:
            exists = path.is_dir()
            nonempty = exists and any(path.iterdir())
        except OSError:
            exists = False
            nonempty = False
        payload = {**payload, "path_exists": exists, "path_nonempty": nonempty}
    return payload


def summary() -> dict[str, Any]:
    games = list_game_data()
    active = list_jobs(active_only=True, limit=200)
    recent = list_jobs(active_only=False, limit=20)
    failed_recent = sum(1 for item in recent if str(item.get("status")) == "failed")
    return {
        "game_data_root": str(GAME_DATA_ROOT),
        "installed_count": len(games),
        "active_jobs": len(active),
        "failed_recent_jobs": failed_recent,
    }


__all__ = [
    "GAME_DATA_ROOT",
    "GAME_STATE_ROOT",
    "HISTORY_ROOT",
    "JOB_ROOT",
    "archive_job",
    "get_game_data",
    "get_job",
    "job_paths",
    "list_game_data",
    "list_jobs",
    "read_json",
    "record_game_data",
    "summary",
    "write_json",
]
