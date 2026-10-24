"""Persist Agent-authenticated, ownership-validated *current* NeoForge proof.

The current observation is not a historical recovery event and MUST NOT
implicitly authorize customer warning suppression.
"""
from __future__ import annotations
import hashlib
from typing import Any
from universal_event_repository import UniversalEventRepository


def persist_current_neoforge_attestations(backend: Any, claims: list[dict[str, Any]]) -> dict[str, int]:
    events = UniversalEventRepository(backend)
    seen: set[str] = set()
    created = 0
    for item in claims[:128]:
        if not isinstance(item, dict) or item.get("kind") != "MinecraftNeoForgeCurrentAttestation":
            continue
        agent, instance, version, observed = (item.get(key) for key in
                                              ("agent_id", "instance_id", "loader_version", "observed_at"))
        if not all(isinstance(value, str) and value for value in (agent, instance, version, observed)):
            continue
        digest = hashlib.sha256("\0".join((agent, instance, version, observed)).encode()).hexdigest()
        event_id = "minecraft-neoforge-current-" + digest
        if event_id in seen:
            continue
        seen.add(event_id)
        result = events.publish({
            "event_id": event_id,
            "event_type": "MINECRAFT_NEOFORGE_CURRENT_VERIFIED",
            "occurred_at": observed,
            "source": "controller.authenticated_agent_current_neoforge",
            "source_id": agent,
            "agent_id": agent,
            "instance_id": instance,
            "severity": "info",
            "data": {"loader_version": version, "proof_scope": "current_runtime_only"},
        })
        created += int(result["created"])
    return {"accepted": len(seen), "created": created}
