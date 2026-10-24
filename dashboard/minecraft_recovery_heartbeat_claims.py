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
