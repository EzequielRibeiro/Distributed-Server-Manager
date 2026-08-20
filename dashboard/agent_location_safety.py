#!/usr/bin/env python3
"""Safety boundary for Agent location changes.

Location is placement metadata. Moving it must never re-parent, delete or rewrite
existing instances owned by the Agent.
"""

from __future__ import annotations

from typing import Any

from agent_location_api import set_agent_location_for_user
from alert_repository import AlertSession, dialect_for_backend


def _instance_ids(backend, agent_id: str) -> list[str]:
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            rows = session.execute(
                "SELECT id FROM instances WHERE agent_id=" + ph + " ORDER BY id",
                (agent_id,),
            ).fetchall()
        finally:
            session.close()
    return [str(row["id"]) for row in rows]


def safely_set_agent_location_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    agent_id = str(payload.get("agent_id", "")).strip()
    before = _instance_ids(backend, agent_id) if agent_id else []
    result = set_agent_location_for_user(user, backend, payload)
    after = _instance_ids(backend, str(result["agent_id"]))
    if before != after:
        raise RuntimeError("Agent location change modified instance ownership")
    result["instances_preserved"] = len(after)
    result["instance_ids_preserved"] = after
    return result
