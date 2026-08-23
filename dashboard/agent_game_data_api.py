#!/usr/bin/env python3
"""Controller-side orchestration for Agent-owned game-data operations."""
from __future__ import annotations
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any
from agent_game_data_repository import AgentGameDataRepository

_ENVIRONMENT_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SELECTOR = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
_FILE_OPERATIONS = {"list", "read", "write", "create", "mkdir", "rename", "delete", "upload"}


def _require_admin(user: dict[str, Any] | None) -> None:
    if not user or str(user.get("role", "")).lower() != "admin":
        raise PermissionError("administrator access required")


def _safe_relative_path(value: Any, *, allow_empty: bool = True) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        if allow_empty: return ""
        raise ValueError("path is required")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must remain inside game-data root")
    if len(text) > 1024:
        raise ValueError("path is too long")
    return path.as_posix()


def prepare_runtime_selection(root: Path, environment_id: str, selector: str) -> dict[str, Any]:
    environment_id = str(environment_id or "").strip(); selector = str(selector or "current").strip()
    if not _ENVIRONMENT_ID.fullmatch(environment_id): raise ValueError("valid environment_id is required")
    if not _SELECTOR.fullmatch(selector): raise ValueError("valid selector is required")
    catalog = root / "installer" / "catalog.sh"
    if not catalog.is_file(): raise RuntimeError("catalog installer is unavailable")
    completed = subprocess.run([str(catalog), "runtime", "prepare", environment_id, selector, "--json"], cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "runtime resolution failed").strip(); raise RuntimeError(detail[:2000])
    try: selection = json.loads(completed.stdout)
    except json.JSONDecodeError as exc: raise RuntimeError("catalog returned an invalid runtime selection") from exc
    if not isinstance(selection, dict) or selection.get("kind") != "RuntimeSelection": raise RuntimeError("catalog returned an invalid runtime selection")
    return selection


def _repository(backend) -> AgentGameDataRepository:
    repository = AgentGameDataRepository(backend); repository.initialize(); return repository


def queue_game_data_operation(user: dict[str, Any] | None, payload: dict[str, Any] | None, *, backend, root: Path) -> dict[str, Any]:
    _require_admin(user); body = payload if isinstance(payload, dict) else {}
    agent_id = str(body.get("agent_id") or "").strip(); environment_id = str(body.get("environment_id") or "").strip(); selector = str(body.get("selector") or "current").strip(); action = str(body.get("action") or "install").strip().lower()
    if not agent_id: raise ValueError("agent_id is required")
    selection = prepare_runtime_selection(root, environment_id, selector)
    return _repository(backend).enqueue(agent_id=agent_id, action=action, environment_id=environment_id, selector=selector, selection=selection, requested_by=str(user.get("username") or user.get("id") or "admin"))


def queue_game_data_file_operation(user: dict[str, Any] | None, payload: dict[str, Any] | None, *, backend, root: Path) -> dict[str, Any]:
    _require_admin(user); body = payload if isinstance(payload, dict) else {}
    agent_id = str(body.get("agent_id") or "").strip(); environment_id = str(body.get("environment_id") or "").strip(); selector = str(body.get("selector") or "current").strip(); operation = str(body.get("operation") or "").strip().lower()
    if not agent_id: raise ValueError("agent_id is required")
    if operation not in _FILE_OPERATIONS: raise ValueError("invalid file operation")
    path = _safe_relative_path(body.get("path"), allow_empty=operation == "list")
    file_operation: dict[str, Any] = {"action": operation, "path": path}
    if operation in {"write", "create"}:
        content = str(body.get("content") or "")
        if len(content.encode("utf-8")) > 1024 * 1024: raise ValueError("content exceeds editable text limit")
        file_operation["content"] = content
    elif operation == "rename":
        file_operation["destination"] = _safe_relative_path(body.get("destination"), allow_empty=False)
    elif operation == "delete":
        file_operation["recursive"] = bool(body.get("recursive"))
    elif operation == "upload":
        encoded = str(body.get("content_base64") or "")
        if len(encoded) > 48 * 1024 * 1024: raise ValueError("upload payload exceeds size limit")
        file_operation["content_base64"] = encoded
    selection = prepare_runtime_selection(root, environment_id, selector)
    selection = dict(selection); selection["_file_operation"] = file_operation
    job = _repository(backend).enqueue(agent_id=agent_id, action="file-" + operation, environment_id=environment_id, selector=selector, selection=selection, requested_by=str(user.get("username") or user.get("id") or "admin"))
    return job


def game_data_job_status(user: dict[str, Any] | None, *, backend, job_id: str | None = None, agent_id: str | None = None) -> dict[str, Any]:
    _require_admin(user); repository = _repository(backend)
    if job_id: return repository.snapshot(str(job_id))
    if not agent_id: raise ValueError("job_id or agent_id is required")
    return {"jobs": repository.list_for_agent(str(agent_id))}

__all__ = ["game_data_job_status", "prepare_runtime_selection", "queue_game_data_file_operation", "queue_game_data_operation"]
