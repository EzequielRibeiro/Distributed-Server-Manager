#!/usr/bin/env python3
"""Read-only Controller view of Agent game-data inventory derived from reported jobs."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from agent_game_data_repository import AgentGameDataRepository

GAME_DATA_INVENTORY_PATH = "/api/agents/game-data/inventory"


def _require_admin(user: dict[str, Any] | None) -> None:
    if not user or str(user.get("role", "")).lower() != "admin":
        raise PermissionError("administrator access required")


def _inventory_for_agent(*, backend, agent_id: str) -> dict[str, Any]:
    repository = AgentGameDataRepository(backend)
    repository.initialize()
    jobs = repository.list_for_agent(agent_id, limit=200)
    latest_by_environment: dict[str, dict[str, Any]] = {}
    installed_by_environment: dict[str, dict[str, Any]] = {}
    for job in jobs:
        environment_id = str(job.get("environment_id") or "").strip()
        if not environment_id:
            continue
        latest_by_environment.setdefault(environment_id, job)
        if environment_id in installed_by_environment:
            continue
        if str(job.get("status") or "").lower() != "completed":
            continue
        action = str(job.get("action") or "").lower()
        if action not in {"install", "update", "verify"}:
            continue
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        selection = job.get("selection") if isinstance(job.get("selection"), dict) else {}
        installed_by_environment[environment_id] = {
            "environment_id": environment_id,
            "game": result.get("game") or selection.get("game"),
            "provider": result.get("provider") or selection.get("provider"),
            "version": result.get("version") or selection.get("version"),
            "target_path": result.get("target_path"),
            "last_action": action,
            "last_job_id": job.get("job_id"),
            "completed_at": job.get("completed_at") or job.get("updated_at"),
        }
    items = []
    for environment_id, item in installed_by_environment.items():
        latest = latest_by_environment.get(environment_id) or {}
        items.append({
            **item,
            "latest_status": latest.get("status"),
            "latest_action": latest.get("action"),
            "latest_error": latest.get("last_error"),
            "latest_job_id": latest.get("job_id"),
        })
    items.sort(key=lambda item: (str(item.get("game") or ""), str(item.get("environment_id") or "")))
    active_jobs = sum(1 for job in jobs if str(job.get("status") or "").lower() in {"queued", "delivered", "running"})
    return {
        "agent_id": agent_id,
        "installed_count": len(items),
        "active_jobs": active_jobs,
        "items": items,
    }


def dispatch_catalog_game_data_inventory_get(
    path: str,
    query_string: str,
    *,
    user: dict[str, Any] | None,
    backend,
) -> tuple[int, dict[str, Any]] | None:
    if path != GAME_DATA_INVENTORY_PATH:
        return None
    try:
        _require_admin(user)
        query = parse_qs(query_string, keep_blank_values=True)
        agent_id = str((query.get("agent_id") or [""])[0]).strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        return 200, _inventory_for_agent(backend=backend, agent_id=agent_id)
    except PermissionError as exc:
        return 403, {"error": "forbidden", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "game_data_inventory_failed", "message": "Não foi possível consultar o inventário de game-data."}


__all__ = ["GAME_DATA_INVENTORY_PATH", "dispatch_catalog_game_data_inventory_get"]
