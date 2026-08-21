#!/usr/bin/env python3
"""Administrative service contract for Agent-owned instance provisioning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from instance_launch_profile import resolve_launch_profile


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def queue_instance_provisioning(payload: dict[str, Any] | None, *, user, backend, root: Path) -> dict[str, Any]:
    actor = _require_admin(user)
    body = payload if isinstance(payload, dict) else {}
    action = str(body.get("action") or "").strip().lower()
    runtime = None
    if action in {"provision", "reconcile"}:
        runtime_id = str(body.get("runtime_id") or "").strip()
        if not runtime_id:
            raise ValueError("runtime_id is required")
        runtime = resolve_launch_profile(Path(root), runtime_id)
    repository = AgentInstanceProvisioningRepository(backend)
    repository.initialize()
    return repository.enqueue(
        agent_id=str(body.get("agent_id") or ""),
        instance_id=str(body.get("instance_id") or ""),
        action=action,
        runtime=runtime,
        requested_by=str(actor.get("username") or actor.get("id") or "admin"),
    )


def instance_provisioning_status(job_id: str, *, user, backend) -> dict[str, Any]:
    _require_admin(user)
    job_id = str(job_id or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    repository = AgentInstanceProvisioningRepository(backend)
    repository.initialize()
    return repository.snapshot(job_id)


__all__ = ["instance_provisioning_status", "queue_instance_provisioning"]
