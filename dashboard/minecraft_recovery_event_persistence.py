"""Persist authenticated recovery claims as immutable, idempotent audit events.

Does not revise terminal provisioning, alter instance health, or authorize UI
suppression. Caller supplies post-authentication, server-owned sanitized claims.
"""
from __future__ import annotations
import hashlib
from typing import Any
from universal_event_repository import UniversalEventRepository


def persist_recovery_claims(backend: Any, claims: list[dict[str, Any]]) -> dict[str, int]:
    events = UniversalEventRepository(backend)
    recorded = 0
    seen: set[str] = set()
    for claim in claims:
        agent = str(claim.get("agent_id") or "")
        instance = str(claim.get("instance_id") or "")
        recovered = str(claim.get("recovered_at") or "")
        if not (agent and instance and recovered) or claim.get("status") != "recovered":
            continue
        # Stable ID prevents heartbeat replays from duplicating recovery events.
        digest = hashlib.sha256(
            "\0".join((agent, instance, "minecraft_serverpack_migration", recovered)).encode()
        ).hexdigest()
        event_id = f"minecraft-recovery-{digest}"
        if event_id in seen:
            continue
        seen.add(event_id)
        result = events.publish({
            "event_id": event_id,
            "event_type": "MINECRAFT_SERVERPACK_MIGRATION_RECOVERED",
            "occurred_at": recovered,
            "source": "controller.authenticated_agent_recovery",
            "source_id": agent,
            "agent_id": agent,
            "instance_id": instance,
            "severity": "info",
            "data": {
                "filesystem_status": claim.get("filesystem_status"),
                "original_loader_version": claim.get("original_loader_version"),
                "observed_at": claim.get("observed_at"),
            },
        })
        recorded += int(result["created"])
    return {"accepted": len(seen), "created": recorded}
