"""Validate present-state NeoForge attestations at the authenticated heartbeat boundary.

This is not a historical migration recovery claim and grants no UI suppression.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any


def current_attestations_from_heartbeat(
    body: dict[str, Any] | None, *,
    authenticated_agent_id: str,
    owned_instance_ids: set[str],
) -> list[dict[str, Any]]:
    if not authenticated_agent_id or not isinstance(body, dict):
        return []
    entries = body.get("minecraft_current_neoforge_attestations")
    if not isinstance(entries, list) or len(entries) > 128:
        return []
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        instance = item.get("instance_id")
        version = item.get("loader_version")
        timestamp = item.get("observed_at")
        if (not isinstance(instance, str) or instance not in owned_instance_ids
                or instance in seen or item.get("agent_id") != authenticated_agent_id
                or item.get("kind") != "MinecraftNeoForgeCurrentAttestation"
                or item.get("verified") is not True
                or not isinstance(version, str)
                or not (3 <= len(version.split(".")) <= 6)
                or any(not part.isdigit() or len(part) > 8 for part in version.split("."))
                or not isinstance(timestamp, str)):
            continue
        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                continue
            observed = observed.astimezone(timezone.utc)
        except ValueError:
            continue
        if observed > datetime.now(timezone.utc):
            continue
        accepted.append({"kind": "MinecraftNeoForgeCurrentAttestation",
                         "agent_id": authenticated_agent_id,
                         "instance_id": instance,
                         "loader_version": version,
                         "observed_at": observed.isoformat().replace("+00:00", "Z")})
        seen.add(instance)
    return accepted
