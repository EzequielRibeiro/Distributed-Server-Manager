"""Conservative read-only assessment of current NeoForge evidence.

Never claims a historic Server Pack migration was recovered.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        item = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return item.astimezone(timezone.utc) if item.tzinfo else None
    except ValueError:
        return None



def current_neoforge_assessment(backend: Any, *, instance_id: str, agent_id: str) -> dict[str, Any]:
    """Load only Controller-owned records; never authorize suppression of history."""
    from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
    from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
    from universal_event_repository import UniversalEventRepository

    failed = AgentInstanceProvisioningRepository(backend).latest_for_instance(instance_id)
    events = UniversalEventRepository(backend).list_events(
        limit=100, event_type="MINECRAFT_NEOFORGE_CURRENT_VERIFIED",
        agent_id=agent_id, instance_id=instance_id)
    rows = AgentInstanceRuntimeHealthRepository(backend).list_for_agent(agent_id)
    health = next((row for row in rows if row.get("instance_id") == instance_id), None)
    return assess_current_neoforge(
        agent_id=agent_id, instance_id=instance_id, failed_provision=failed,
        attestation_events=events, runtime_health=health)


def assess_current_neoforge(*, agent_id: str, instance_id: str,
                           failed_provision: dict[str, Any] | None,
                           attestation_events: list[dict[str, Any]],
                           runtime_health: dict[str, Any] | None) -> dict[str, Any]:
    result = {"status": "unverified", "current_loader_verified": False,
              "healthy_after_attestation": False, "historical_recovery_verified": False,
              "allow_clear_previous_failure": False}
    if (not isinstance(failed_provision, dict)
            or failed_provision.get("status") != "failed"
            or failed_provision.get("agent_id") != agent_id
            or failed_provision.get("instance_id") != instance_id):
        return result
    failure_at = _time(failed_provision.get("completed_at") or failed_provision.get("updated_at"))
    if failure_at is None:
        return result
    # The expected build must come from the Controller's saved provisioning
    # request, never from the Agent attestation being assessed.
    request = failed_provision.get("request")
    selection = ((request.get("content") or {}).get("selection")
                 if isinstance(request, dict) and isinstance(request.get("content"), dict)
                 else None)
    expected_version = (selection.get("build") or selection.get("loader_version")
                        if isinstance(selection, dict) else None)
    if not isinstance(expected_version, str) or not expected_version.strip():
        return result
    expected_version = expected_version.strip()
    matching = []
    for event in attestation_events[:100]:
        if (not isinstance(event, dict)
                or event.get("event_type") != "MINECRAFT_NEOFORGE_CURRENT_VERIFIED"
                or event.get("source") != "controller.authenticated_agent_current_neoforge"
                or event.get("agent_id") != agent_id
                or event.get("instance_id") != instance_id):
            continue
        details = event.get("data")
        if (not isinstance(details, dict)
                or details.get("proof_scope") != "current_runtime_only"
                or details.get("loader_version") != expected_version):
            continue
        observed_at = _time(event.get("occurred_at"))
        if observed_at and observed_at > failure_at and observed_at <= datetime.now(timezone.utc):
            matching.append(observed_at)
    if not matching:
        return result
    latest = max(matching)
    result["current_loader_verified"] = True
    if not isinstance(runtime_health, dict) or runtime_health.get("instance_id") != instance_id:
        result["status"] = "awaiting_current_health"
        return result
    health_at = _time(runtime_health.get("reported_at"))
    if not health_at or health_at < latest or health_at > datetime.now(timezone.utc):
        result["status"] = "awaiting_current_health"
        return result
    result["healthy_after_attestation"] = (
        str(runtime_health.get("observed_state") or "").lower() == "running"
        and str(runtime_health.get("reconcile_status") or "").lower() == "healthy"
        and str(runtime_health.get("health") or "").lower() in {"healthy", "ok"})
    result["status"] = "current_runtime_verified" if result["healthy_after_attestation"] else "current_runtime_unhealthy"
    return result
