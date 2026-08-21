#!/usr/bin/env python3
"""Administrative service boundary for the Universal Event Platform."""

from __future__ import annotations

from typing import Any

from universal_event_repository import UniversalEventRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def list_events(*, user, backend, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    _require_admin(user)
    values = filters if isinstance(filters, dict) else {}
    repo = UniversalEventRepository(backend)
    repo.initialize()
    events = repo.list_events(
        limit=int(values.get("limit") or 100),
        event_type=values.get("event_type"),
        agent_id=values.get("agent_id"),
        instance_id=values.get("instance_id"),
        severity=values.get("severity"),
        correlation_id=values.get("correlation_id"),
    )
    return {"schema_version": 1, "kind": "CapivaraUniversalEventList", "events": events, "count": len(events)}


def get_event(event_id: str, *, user, backend) -> dict[str, Any]:
    _require_admin(user)
    event_id = str(event_id or "").strip()
    if not event_id:
        raise ValueError("event_id is required")
    repo = UniversalEventRepository(backend)
    repo.initialize()
    event = repo.get(event_id)
    if event is None:
        raise KeyError(event_id)
    return event


def publish_event(payload: dict[str, Any] | None, *, user, backend) -> dict[str, Any]:
    actor = _require_admin(user)
    body = dict(payload or {})
    body["actor_type"] = body.get("actor_type") or "dashboard_user"
    body["actor_id"] = body.get("actor_id") or actor.get("username") or actor.get("id") or "admin"
    repo = UniversalEventRepository(backend)
    repo.initialize()
    return repo.publish(body)


__all__ = ["get_event", "list_events", "publish_event"]
