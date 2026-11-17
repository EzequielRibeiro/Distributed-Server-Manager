"""Authenticate-bound extraction of recovery statements from Agent heartbeat.

The HTTP dispatcher must call this ONLY after credential authentication.
No persistence, state mutation, or authorization to suppress UI warnings.
"""
from __future__ import annotations
from typing import Any

from minecraft_recovery_observation_contract import validate_recovery_observation


def recovery_claims_from_heartbeat(
    body: dict[str, Any] | None, *,
    authenticated_agent_id: str,
    owned_instance_ids: set[str],
) -> list[dict[str, Any]]:
    if not authenticated_agent_id or not isinstance(body, dict):
        return []
    entries = body.get("minecraft_recovery_observations")
    if not isinstance(entries, list) or len(entries) > 128:
        return []
    accepted = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        instance_id = entry.get("instance_id")
        if not isinstance(instance_id, str) or instance_id not in owned_instance_ids or instance_id in seen:
            continue
        result = validate_recovery_observation(
            entry,
            authenticated_agent_id=authenticated_agent_id,
            expected_instance_id=instance_id,
        )
        if result is not None:
            accepted.append(result)
            seen.add(instance_id)
    return accepted


def owned_instance_ids_for_agent(backend: Any, *, agent_id: str) -> set[str]:
    """Resolve ownership from Controller persistence, never from heartbeat body."""
    if not agent_id:
        return set()
    from alert_repository import AlertSession, dialect_for_backend
    dialect = dialect_for_backend(backend)
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            rows = session.execute(
                f"SELECT id FROM instances WHERE agent_id={dialect.placeholder}",
                (agent_id,),
            ).fetchall()
            return {str(row["id"]) for row in rows}
        finally:
            session.close()


def validated_heartbeat_recovery_claims(
    backend: Any, body: dict[str, Any] | None, *, authenticated_agent_id: str,
) -> list[dict[str, Any]]:
    """Read-only binding of validated claims to server-owned instances."""
    owned = owned_instance_ids_for_agent(backend, agent_id=authenticated_agent_id)
    return recovery_claims_from_heartbeat(
        body, authenticated_agent_id=authenticated_agent_id,
        owned_instance_ids=owned,
    )
