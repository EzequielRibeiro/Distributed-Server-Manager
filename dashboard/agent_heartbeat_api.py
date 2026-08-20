#!/usr/bin/env python3
"""Transport-neutral Agent inventory/heartbeat service boundary.

The authenticated Agent identity is supplied by the transport layer. This
module deliberately does not invent an authentication mechanism; secure remote
pairing can bind credentials to ``authenticated_agent_id`` later.
"""

from __future__ import annotations

from typing import Any

from agent_runtime_repository import AgentRuntimeRepository


def record_agent_heartbeat(
    authenticated_agent_id: str,
    payload: dict[str, Any] | None,
    *,
    backend,
) -> dict[str, Any]:
    agent_id = str(authenticated_agent_id or "").strip()
    if not agent_id:
        raise PermissionError("authenticated Agent identity required")

    body = payload if isinstance(payload, dict) else {}
    claimed = str(body.get("agent_id") or agent_id).strip()
    if claimed != agent_id:
        raise PermissionError("Agent identity mismatch")

    repository = AgentRuntimeRepository(backend)
    repository.initialize()

    inventory_fields = {
        "hostname": body.get("hostname"),
        "os_name": body.get("os") or body.get("os_name"),
        "architecture": body.get("architecture"),
        "capivara_version": body.get("capivara_version"),
        "address": body.get("address"),
        "fingerprint": body.get("fingerprint"),
        "capabilities": body.get("capabilities"),
        "cpu": body.get("cpu"),
        "ram_total_bytes": body.get("ram_total_bytes"),
        "storage": body.get("storage"),
        "heartbeat_interval_seconds": int(body.get("heartbeat_interval_seconds", 30)),
        "degraded_after_seconds": int(body.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(body.get("offline_after_seconds", 120)),
    }

    if any(
        inventory_fields[name] is not None
        for name in (
            "hostname", "os_name", "architecture", "capivara_version",
            "address", "fingerprint", "capabilities", "cpu",
            "ram_total_bytes", "storage",
        )
    ):
        repository.upsert_inventory(agent_id=agent_id, **inventory_fields)

    last_seen = repository.heartbeat(agent_id)
    return {
        "agent_id": agent_id,
        "health_status": "online",
        "last_seen": last_seen,
    }
