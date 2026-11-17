"""Read-only, fail-closed Agent recovery observation builder.

This is evidence construction only. Controller authentication must be verified
at ingestion; this module never claims a transport is authenticated.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def recovery_observation(
    operation: dict[str, Any] | None,
    *,
    instance_id: str,
    agent_id: str,
    observed_at: str,
) -> dict[str, Any] | None:
    """Expose a narrow recovered-journal statement without secrets or health claims."""
    if not isinstance(operation, dict) or not instance_id or not agent_id:
        return None
    if operation.get("instance_id") != instance_id or operation.get("agent_id") != agent_id:
        return None
    if operation.get("operation") != "minecraft_serverpack_migration":
        return None
    if operation.get("status") != "recovered":
        return None
    detail = operation.get("recovery")
    if not isinstance(detail, dict):
        return None
    if detail.get("kind") != "MinecraftServerPackMigrationRecovery":
        return None
    if detail.get("filesystem_status") not in ("recovered", "already_recovered"):
        return None
    if detail.get("manual_recovery_required") is not False:
        return None
    version = detail.get("original_loader_version")
    if not isinstance(version, str) or not version.strip():
        return None
    recovered_at = operation.get("recovered_at")
    if not _valid_timestamp(recovered_at) or not _valid_timestamp(observed_at):
        return None
    if datetime.fromisoformat(recovered_at.replace("Z", "+00:00")) > datetime.fromisoformat(observed_at.replace("Z", "+00:00")):
        return None
    return {
        "kind": "MinecraftServerPackRecoveryObservation",
        "schema_version": 1,
        "instance_id": instance_id,
        "agent_id": agent_id,
        "operation": "minecraft_serverpack_migration",
        "status": "recovered",
        "filesystem_status": detail["filesystem_status"],
        "original_loader_version": version,
        "recovered_at": recovered_at,
        "observed_at": observed_at,
        # Intentionally no authenticated_agent_observation, healthy status,
        # or original_loader_verified assertion: trusted ingestion and live
        # independent verification are still required before UI suppression.
    }
