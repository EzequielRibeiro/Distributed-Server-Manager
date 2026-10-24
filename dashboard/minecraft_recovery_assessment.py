"""Read-only Controller recovery assessment using persisted audit and runtime health.

The audit record is not proof that the original NeoForge loader remains valid.
Fail closed until a separately verified loader attestation is available.
"""
from __future__ import annotations
from typing import Any

from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from universal_event_repository import UniversalEventRepository

EVENT_TYPE = "MINECRAFT_SERVERPACK_MIGRATION_RECOVERED"


def recovery_assessment(backend: Any, *, instance_id: str, agent_id: str) -> dict[str, Any]:
    result = {"status": "unverified", "instance_id": instance_id, "agent_id": agent_id,
              "audit_recorded": False, "healthy": False, "loader_verified": False,
              "allow_clear_previous_failure": False}
    if not instance_id or not agent_id:
        return result
    events = UniversalEventRepository(backend).list_events(
        limit=10, event_type=EVENT_TYPE, agent_id=agent_id, instance_id=instance_id)
    matching = [e for e in events if e.get("source") == "controller.authenticated_agent_recovery"
                and e.get("agent_id") == agent_id and e.get("instance_id") == instance_id]
    if not matching:
        return result
    result["audit_recorded"] = True
    rows = AgentInstanceRuntimeHealthRepository(backend).list_for_agent(agent_id)
    observed = next((r for r in rows if r.get("instance_id") == instance_id), None)
    if not observed:
        return result
    result["healthy"] = (
        str(observed.get("observed_state") or "").lower() == "running"
        and str(observed.get("reconcile_status") or "").lower() == "healthy"
        and str(observed.get("health") or "").lower() in {"healthy", "ok"}
    )
    # Intentionally no assumed loader verification: this function is read-only
    # and cannot prove that the instance-local launcher is correct.
    return result
