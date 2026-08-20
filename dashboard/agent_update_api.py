#!/usr/bin/env python3
"""RBAC-aware remote Agent update planning and rollout status."""

from __future__ import annotations

from typing import Any

from agent_update_repository import AgentUpdateRepository
from alert_repository import AlertSession, dialect_for_backend


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()


def _scoped_agents(user: dict[str, Any], backend, requested: list[str]) -> list[str]:
    role = _role(user)
    ids = [str(item).strip() for item in requested if str(item).strip()]
    if not ids:
        raise ValueError("agent_ids is required")
    dialect = dialect_for_backend(backend)
    placeholders = dialect.parameters(len(ids))
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            rows = session.execute(
                f"SELECT id,controller_id FROM agents WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        finally:
            session.close()
    found = {str(row["id"]): str(row["controller_id"]) for row in rows}
    if set(found) != set(ids):
        raise ValueError("one or more Agents do not exist")
    if role == "admin":
        return ids
    if role == "controller":
        scope = str(user.get("scope_id", "")).strip()
        if not scope or any(controller_id != scope for controller_id in found.values()):
            raise PermissionError("Agent is outside controller scope")
        return ids
    raise PermissionError("Agent update administration is not permitted")


def create_agent_rollout_for_user(user, backend, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    agent_ids = _scoped_agents(user or {}, backend, list(payload.get("agent_ids") or []))
    repository = AgentUpdateRepository(backend)
    repository.initialize()
    return repository.create_rollout(
        agent_ids,
        desired_version=str(payload.get("desired_version", "")).strip(),
        channel=str(payload.get("update_channel", "stable")).strip().lower(),
        batch_size=int(payload.get("batch_size", 1) or 1),
    )


def set_agent_update_channel_for_user(user, backend, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    agent_id = _scoped_agents(user or {}, backend, [str(payload.get("agent_id", ""))])[0]
    repository = AgentUpdateRepository(backend)
    repository.initialize()
    return repository.set_channel(agent_id, str(payload.get("update_channel", "")))


def agent_update_status_for_user(user, backend, agent_id: str) -> dict[str, Any]:
    agent_id = _scoped_agents(user or {}, backend, [agent_id])[0]
    repository = AgentUpdateRepository(backend)
    repository.initialize()
    return repository.snapshot(agent_id)


__all__ = [
    "create_agent_rollout_for_user",
    "set_agent_update_channel_for_user",
    "agent_update_status_for_user",
]
