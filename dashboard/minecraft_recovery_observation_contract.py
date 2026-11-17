"""Untrusted Agent recovery observation validation at Controller boundary.

The calling HTTP layer must authenticate the Agent session first and pass its
server-resolved identity. This validator does not read or write persistence.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def validate_recovery_observation(
    payload: dict[str, Any] | None, *,
    authenticated_agent_id: str, expected_instance_id: str,
) -> dict[str, Any] | None:
    """Return a sanitized claim, never an authorization to hide a failure."""
    if not isinstance(payload, dict) or not authenticated_agent_id or not expected_instance_id:
        return None
    if payload.get("kind") != "MinecraftServerPackRecoveryObservation" or payload.get("schema_version") != 1:
        return None
    if payload.get("agent_id") != authenticated_agent_id or payload.get("instance_id") != expected_instance_id:
        return None
    if payload.get("operation") != "minecraft_serverpack_migration" or payload.get("status") != "recovered":
        return None
    if payload.get("filesystem_status") not in {"recovered", "already_recovered"}:
        return None
    loader = payload.get("original_loader_version")
    if not isinstance(loader, str) or not (1 <= len(loader) <= 80) or any(ch not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.+-_" for ch in loader):
        return None
    recovered_at, observed_at = _timestamp(payload.get("recovered_at")), _timestamp(payload.get("observed_at"))
    if recovered_at is None or observed_at is None or recovered_at > observed_at:
        return None
    proof = payload.get("loader_proof")
    claimed_loader = (
        isinstance(proof, dict) and proof.get("verified") is True
        and proof.get("instance_id") == expected_instance_id
        and proof.get("agent_id") == authenticated_agent_id
        and proof.get("loader_version") == loader
        and proof.get("evidence") == "instance-local-launcher"
    )
    return {
        "instance_id": expected_instance_id,
        "agent_id": authenticated_agent_id,
        "operation": "minecraft_serverpack_migration",
        "status": "recovered",
        "filesystem_status": payload["filesystem_status"],
        "original_loader_version": loader,
        "recovered_at": payload["recovered_at"],
        "observed_at": payload["observed_at"],
        "agent_reported_loader_proof": bool(claimed_loader),
        # This validates ownership and shape only. A separate real health
        # observation and loader check are required before UI suppression.
    }
