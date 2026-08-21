#!/usr/bin/env python3
"""Administrative service contract for Agent-owned instance observations."""

from __future__ import annotations

from typing import Any

from agent_instance_runtime_repository import AgentInstanceRuntimeRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    user = user if isinstance(user, dict) else {}
    if str(user.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return user


def queue_instance_observation(payload: dict[str, Any] | None, *, user, backend) -> dict[str, Any]:
    actor = _require_admin(user)
    body = payload if isinstance(payload, dict) else {}
    repository = AgentInstanceRuntimeRepository(backend)
    repository.initialize()
    return repository.enqueue(
        agent_id=str(body.get("agent_id") or ""),
        instance_id=str(body.get("instance_id") or ""),
        action=str(body.get("action") or ""),
        requested_by=str(actor.get("username") or actor.get("id") or "admin"),
    )


def instance_observation_status(command_id: str, *, user, backend) -> dict[str, Any]:
    _require_admin(user)
    command_id = str(command_id or "").strip()
    if not command_id:
        raise ValueError("command_id is required")
    repository = AgentInstanceRuntimeRepository(backend)
    repository.initialize()
    return repository.snapshot(command_id)


__all__ = ["instance_observation_status", "queue_instance_observation"]
