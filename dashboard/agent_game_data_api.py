#!/usr/bin/env python3
"""Controller-side orchestration for Agent-owned game-data operations."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

from agent_game_data_repository import AgentGameDataRepository

_ENVIRONMENT_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SELECTOR = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


def _require_admin(user: dict[str, Any] | None) -> None:
    if not user or str(user.get("role", "")).lower() != "admin":
        raise PermissionError("administrator access required")


def prepare_runtime_selection(root: Path, environment_id: str, selector: str) -> dict[str, Any]:
    environment_id = str(environment_id or "").strip()
    selector = str(selector or "current").strip()
    if not _ENVIRONMENT_ID.fullmatch(environment_id):
        raise ValueError("valid environment_id is required")
    if not _SELECTOR.fullmatch(selector):
        raise ValueError("valid selector is required")
    catalog = root / "installer" / "catalog.sh"
    if not catalog.is_file():
        raise RuntimeError("catalog installer is unavailable")
    completed = subprocess.run(
        [str(catalog), "runtime", "prepare", environment_id, selector, "--json"],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "runtime resolution failed").strip()
        raise RuntimeError(detail[:2000])
    try:
        selection = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("catalog returned an invalid runtime selection") from exc
    if not isinstance(selection, dict) or selection.get("kind") != "RuntimeSelection":
        raise RuntimeError("catalog returned an invalid runtime selection")
    return selection


def queue_game_data_operation(
    user: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    *,
    backend,
    root: Path,
) -> dict[str, Any]:
    _require_admin(user)
    body = payload if isinstance(payload, dict) else {}
    agent_id = str(body.get("agent_id") or "").strip()
    environment_id = str(body.get("environment_id") or "").strip()
    selector = str(body.get("selector") or "current").strip()
    action = str(body.get("action") or "install").strip().lower()
    if not agent_id:
        raise ValueError("agent_id is required")
    selection = prepare_runtime_selection(root, environment_id, selector)
    repository = AgentGameDataRepository(backend)
    repository.initialize()
    return repository.enqueue(
        agent_id=agent_id,
        action=action,
        environment_id=environment_id,
        selector=selector,
        selection=selection,
        requested_by=str(user.get("username") or user.get("id") or "admin"),
    )


def game_data_job_status(
    user: dict[str, Any] | None,
    *,
    backend,
    job_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    _require_admin(user)
    repository = AgentGameDataRepository(backend)
    repository.initialize()
    if job_id:
        return repository.snapshot(str(job_id))
    if not agent_id:
        raise ValueError("job_id or agent_id is required")
    return {"jobs": repository.list_for_agent(str(agent_id))}


__all__ = ["game_data_job_status", "prepare_runtime_selection", "queue_game_data_operation"]
