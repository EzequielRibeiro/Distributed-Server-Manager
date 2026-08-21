#!/usr/bin/env python3
"""Administrative service contract for B10 instance provisioning."""

from __future__ import annotations

from typing import Any

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    user = user if isinstance(user, dict) else {}
    if str(user.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return user


def queue_instance_provisioning(payload: dict[str, Any] | None, *, user, backend) -> dict[str, Any]:
    actor = _require_admin(user)
    body = payload if isinstance(payload, dict) else {}
    repository = AgentInstanceProvisioningRepository(backend)
    repository.initialize()
    return repository.enqueue(
        agent_id=str(body.get("agent_id") or ""),
        instance_id=str(body.get("instance_id") or ""),
        environment_id=str(body.get("environment_id") or ""),
        selector=str(body.get("selector") or ""),
        selection=body.get("selection") if isinstance(body.get("selection"), dict) else {},
        configuration=body.get("configuration") if isinstance(body.get("configuration"), dict) else {},
        desired_state=str(body.get("desired_state") or "stopped"),
        requested_by=str(actor.get("username") or actor.get("id") or "admin"),
    )


def instance_provisioning_status(provisioning_id: str, *, user, backend) -> dict[str, Any]:
    _require_admin(user)
    provisioning_id = str(provisioning_id or "").strip()
    if not provisioning_id:
        raise ValueError("provisioning_id is required")
    repository = AgentInstanceProvisioningRepository(backend)
    repository.initialize()
    return repository.snapshot(provisioning_id)


__all__ = ["instance_provisioning_status", "queue_instance_provisioning"]
