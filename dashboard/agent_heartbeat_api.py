#!/usr/bin/env python3
"""Transport-neutral Agent inventory/heartbeat service boundary."""

from __future__ import annotations

from typing import Any

from agent_instance_reconciliation_repository import AgentInstanceReconciliationRepository
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from agent_runtime_repository import AgentRuntimeRepository
from universal_event_repository import UniversalEventRepository


def record_agent_heartbeat(authenticated_agent_id: str, payload: dict[str, Any] | None, *, backend) -> dict[str, Any]:
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
        "hostname": body.get("hostname"), "os_name": body.get("os") or body.get("os_name"),
        "architecture": body.get("architecture"), "capivara_version": body.get("capivara_version"),
        "address": body.get("address"), "fingerprint": body.get("fingerprint"),
        "capabilities": body.get("capabilities"), "cpu": body.get("cpu"),
        "ram_total_bytes": body.get("ram_total_bytes"), "storage": body.get("storage"), "network": body.get("network"),
        "heartbeat_interval_seconds": int(body.get("heartbeat_interval_seconds", 30)),
        "degraded_after_seconds": int(body.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(body.get("offline_after_seconds", 120)),
    }
    if any(inventory_fields[name] is not None for name in (
        "hostname", "os_name", "architecture", "capivara_version", "address", "fingerprint",
        "capabilities", "cpu", "ram_total_bytes", "storage", "network",
    )):
        repository.upsert_inventory(agent_id=agent_id, **inventory_fields)

    reconciliation = body.get("instance_reconciliation")
    if isinstance(reconciliation, list):
        projections = AgentInstanceReconciliationRepository(backend)
        projections.initialize()
        projections.apply_inventory(agent_id, reconciliation)

    runtime_health = body.get("instance_runtime_health")
    if isinstance(runtime_health, list):
        health = AgentInstanceRuntimeHealthRepository(backend)
        health.initialize()
        health.apply_inventory(agent_id, runtime_health)

    event_result = {"accepted_event_ids": [], "accepted": 0, "created": 0, "rejected": 0}
    runtime_events = body.get("runtime_events")
    if isinstance(runtime_events, list):
        events = UniversalEventRepository(backend)
        events.initialize()
        event_result = events.ingest_agent_events(agent_id, runtime_events)

    last_seen = repository.heartbeat(agent_id)
    return {
        "agent_id": agent_id,
        "health_status": "online",
        "last_seen": last_seen,
        "accepted_event_ids": event_result["accepted_event_ids"],
        "events_accepted": event_result["accepted"],
        "events_created": event_result["created"],
        "events_rejected": event_result["rejected"],
    }
