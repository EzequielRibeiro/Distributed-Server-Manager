#!/usr/bin/env python3
"""Administrative service boundary for Universal Configuration Platform."""

from __future__ import annotations

from typing import Any

from configuration_repository import ConfigurationRepository
from universal_event_repository import UniversalEventRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def list_configurations(*, user, backend, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    _require_admin(user)
    values = filters if isinstance(filters, dict) else {}
    repo = ConfigurationRepository(backend)
    repo.initialize()
    rows = repo.list_configurations(
        scope_type=values.get("scope_type"),
        scope_id=values.get("scope_id"),
        namespace=values.get("namespace"),
        limit=int(values.get("limit") or 200),
    )
    return {"schema_version": 1, "kind": "CapivaraConfigurationList", "configurations": rows, "count": len(rows)}


def get_configuration(*, user, backend, scope_type: str, scope_id: str | None, namespace: str) -> dict[str, Any]:
    _require_admin(user)
    repo = ConfigurationRepository(backend)
    repo.initialize()
    row = repo.get(scope_type=scope_type, scope_id=scope_id, namespace=namespace)
    if row is None:
        raise KeyError(namespace)
    return row


def set_configuration(payload: dict[str, Any] | None, *, user, backend) -> dict[str, Any]:
    actor = _require_admin(user)
    body = dict(payload or {})
    repo = ConfigurationRepository(backend)
    repo.initialize()
    actor_id = str(actor.get("username") or actor.get("id") or "admin")
    result = repo.put(body, updated_by=actor_id)
    if result["changed"]:
        event_repo = UniversalEventRepository(backend)
        event_repo.initialize()
        row = result["configuration"]
        event_repo.publish({
            "event_type": "CONFIGURATION_UPDATED",
            "source": "controller.configuration",
            "severity": "info",
            "actor_type": "dashboard_user",
            "actor_id": actor_id,
            "agent_id": row.get("scope_id") if row.get("scope_type") == "agent" else None,
            "instance_id": row.get("scope_id") if row.get("scope_type") == "instance" else None,
            "data": {
                "configuration_id": row["configuration_id"],
                "scope_type": row["scope_type"],
                "scope_id": row.get("scope_id"),
                "namespace": row["namespace"],
                "revision": row["revision"],
                "checksum": row["checksum"],
            },
        })
    return result


def resolve_configuration(*, user, backend, agent_id: str, instance_id: str | None = None) -> dict[str, Any]:
    _require_admin(user)
    repo = ConfigurationRepository(backend)
    repo.initialize()
    rows = repo.resolve_for_instance(agent_id, instance_id) if instance_id else repo.resolve_for_agent(agent_id)
    return {"schema_version": 1, "kind": "CapivaraResolvedConfigurationList", "configurations": rows, "count": len(rows)}


__all__ = ["get_configuration", "list_configurations", "resolve_configuration", "set_configuration"]
