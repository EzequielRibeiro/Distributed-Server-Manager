"""Fail-closed evaluation of Agent recovery evidence for a historical provisioning failure.

This module does not authorize migration, rewrite provisioning history or inspect
production files. Callers must supply independently authenticated Agent evidence.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp.astimezone(timezone.utc) if timestamp.tzinfo else None


def recovered_previous_failure(
    provisioning: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    *,
    expected_instance_id: str,
    expected_agent_id: str,
    live_state: str,
    reconcile_status: str,
) -> bool:
    """True only with bound, newer, verified recovery and a healthy observation.

    Evidence must have been validated by the authenticated Agent observation
    ingestion layer; user/browser supplied payloads MUST NOT be passed here.
    """
    if not isinstance(provisioning, dict) or not isinstance(evidence, dict):
        return False
    if provisioning.get("status") != "failed":
        return False
    if not expected_instance_id or not expected_agent_id:
        return False
    if (provisioning.get("instance_id") != expected_instance_id or
        provisioning.get("agent_id") != expected_agent_id or
        evidence.get("instance_id") != expected_instance_id or
        evidence.get("agent_id") != expected_agent_id):
        return False
    if evidence.get("authenticated_agent_observation") is not True:
        return False
    if (evidence.get("operation") != "minecraft_serverpack_migration" or
        evidence.get("status") != "recovered" or
        evidence.get("filesystem_status") not in {"recovered", "already_recovered"} or
        evidence.get("original_loader_verified") is not True):
        return False
    if live_state != "running" or reconcile_status != "healthy":
        return False
    failure_at = _when(provisioning.get("completed_at") or provisioning.get("updated_at"))
    recovered_at = _when(evidence.get("recovered_at"))
    observed_at = _when(evidence.get("observed_at"))
    if not failure_at or not recovered_at or not observed_at:
        return False
    return failure_at < recovered_at <= observed_at
