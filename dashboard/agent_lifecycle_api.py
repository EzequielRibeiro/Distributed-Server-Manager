#!/usr/bin/env python3
"""RBAC-aware Agent registration, pairing and lifecycle administration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_lifecycle_repository import AgentLifecycleRepository, AgentNotFound
from agent_registration_repository import AgentRegistrationRepository
from core.agent_lifecycle import allowed_agent_transitions
from infrastructure_repository import InfrastructureRepository


PAIRING_ACTION_TARGETS = {
    "start": "pairing",
    "approve": "active",
    "reject": "rejected",
    "cancel": "pending",
}


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()


def _controller_scope(
    user: dict[str, Any] | None,
    requested_controller_id: str | None,
) -> str:
    role = _role(user)
    requested = str(requested_controller_id or "").strip()

    if role == "admin":
        if not requested:
            raise ValueError("controller_id is required")
        return requested

    if role == "controller":
        scope_id = str(user.get("scope_id", "")).strip()
        if not scope_id:
            raise PermissionError("controller scope is required")
        if requested and requested != scope_id:
            raise PermissionError("controller is outside user scope")
        return scope_id

    raise PermissionError("agent administration is not permitted")


def _agent_for_user(
    user: dict[str, Any] | None,
    backend,
    agent_id: str,
) -> dict[str, Any]:
    role = _role(user)
    identifier = str(agent_id).strip()
    if not identifier:
        raise ValueError("agent_id is required")

    repository = InfrastructureRepository(backend)
    agent = next(
        (item for item in repository.agents() if str(item["id"]) == identifier),
        None,
    )
    if agent is None:
        raise AgentNotFound(f"Agent not found: {identifier}")

    if role == "admin":
        return agent

    if role == "controller":
        scope_id = str(user.get("scope_id", "")).strip()
        if scope_id and scope_id == str(agent["controller_id"]):
            return agent
        raise PermissionError("agent is outside user scope")

    raise PermissionError("agent administration is not permitted")


def register_agent_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Register an Agent in ``pending`` state under an authorized Controller."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    controller_id = _controller_scope(user, payload.get("controller_id"))
    repository = AgentRegistrationRepository(backend)
    registered = repository.register(
        controller_id=controller_id,
        agent_id=str(payload.get("agent_id", "")),
        node_id=str(payload.get("node_id", "")),
        name=str(payload.get("name", "")),
        metadata_json=str(payload.get("metadata_json", "{}")),
    )
    return {
        "agent_id": registered.agent_id,
        "controller_id": registered.controller_id,
        "node_id": registered.node_id,
        "name": registered.name,
        "status": registered.status,
        "allowed_transitions": sorted(allowed_agent_transitions(registered.status)),
    }


def agent_lifecycle_for_user(
    user: dict[str, Any] | None,
    backend,
    agent_id: str,
) -> dict[str, Any]:
    """Return lifecycle state and legal next transitions for one Agent."""
    agent = _agent_for_user(user, backend, agent_id)
    status = str(agent["status"]).strip().lower()
    return {
        "agent_id": agent["id"],
        "controller_id": agent["controller_id"],
        "status": status,
        "allowed_transitions": sorted(allowed_agent_transitions(status)),
    }


def transition_agent_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply one authorized lifecycle transition."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    agent = _agent_for_user(user, backend, str(payload.get("agent_id", "")))
    target = str(payload.get("target", "")).strip().lower()
    if not target:
        raise ValueError("target is required")

    result = AgentLifecycleRepository(backend).transition(agent["id"], target)
    return {
        "agent_id": agent["id"],
        "controller_id": agent["controller_id"],
        "previous_status": result.current,
        "status": result.target,
        "changed": result.changed,
        "allowed_transitions": sorted(allowed_agent_transitions(result.target)),
    }


def pairing_action_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply a semantic pairing action through the lifecycle state machine."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    action = str(payload.get("action", "")).strip().lower()
    try:
        target = PAIRING_ACTION_TARGETS[action]
    except KeyError as exc:
        raise ValueError("invalid pairing action") from exc

    return transition_agent_for_user(
        user,
        backend,
        {
            "agent_id": payload.get("agent_id"),
            "target": target,
        },
    )
