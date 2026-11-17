"""Fail-closed, read-only evaluation of a failed committed Server Pack migration.

No filesystem writes, process starts, journal transitions, or silent rollback.
The caller must independently attest digests and game-unit state. A positive
result is permission for human review only, never permission to mutate files.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FAILED_ROLLBACK = "migration failed and rollback also failed: manual recovery required"


class CommittedRecoveryAssessmentError(ValueError):
    """Untrusted or inconsistent recovery evidence."""


def assess_failed_committed_migration(
    *,
    instance_id: str,
    agent_id: str,
    operation: Mapping[str, Any],
    journal: Mapping[str, Any],
    active_managed_sha256: str,
    rollback_tree_sha256: str,
    installed_loader_version: str,
    retained_backup_verified: bool,
    game_unit_state: str,
) -> dict[str, Any]:
    """Return a non-actionable evidence assessment; never mutate any input.

    Hashes are supplied by an independent, trusted read-only filesystem probe;
    the journal's claims must not substitute for measurements. An external
    caller must also prove association with the correct instance and Agent.
    """
    if (not isinstance(instance_id, str) or not instance_id.strip()
            or not isinstance(agent_id, str) or not agent_id.strip()
            or not isinstance(operation, Mapping) or not isinstance(journal, Mapping)):
        raise CommittedRecoveryAssessmentError("instance, Agent and journals required")
    if (operation.get("instance_id") != instance_id
            or operation.get("agent_id") != agent_id
            or operation.get("operation") != "minecraft_serverpack_migration"
            or operation.get("status") != "failed"
            or operation.get("error") != _FAILED_ROLLBACK):
        raise CommittedRecoveryAssessmentError("operation is not the matching failed rollback")
    if journal.get("phase") != "committed" or journal.get("kind") != "CapivaraMinecraftServerPackMigrationSwap":
        raise CommittedRecoveryAssessmentError("migration is not a committed Server Pack swap")
    for key, value in (
        ("original_tree_sha256", journal.get("original_tree_sha256")),
        ("staged_managed_sha256", journal.get("staged_managed_sha256")),
        ("active_managed_sha256", active_managed_sha256),
        ("rollback_tree_sha256", rollback_tree_sha256),
    ):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise CommittedRecoveryAssessmentError(f"invalid independent digest: {key}")
    if not isinstance(installed_loader_version, str) or not installed_loader_version:
        raise CommittedRecoveryAssessmentError("independent loader proof required")
    if game_unit_state not in {"active", "inactive", "failed", "unknown"}:
        raise CommittedRecoveryAssessmentError("untrusted game unit state")

    findings: list[str] = []
    if game_unit_state != "inactive":
        findings.append("unit_not_proven_inactive")
    if retained_backup_verified is not True:
        findings.append("retained_backup_not_verified")
    if rollback_tree_sha256 != journal["original_tree_sha256"]:
        findings.append("original_rollback_checkpoint_mismatch")
    if installed_loader_version != journal.get("target_loader_version"):
        findings.append("active_loader_mismatch")
    if active_managed_sha256 != journal["staged_managed_sha256"]:
        findings.append("active_managed_checkpoint_mismatch")

    return {
        "kind": "MinecraftFailedCommittedRecoveryAssessment",
        "schema_version": 1,
        "instance_id": instance_id,
        "agent_id": agent_id,
        "operation_status": "failed",
        "swap_phase": "committed",
        "read_only": True,
        "safe_to_change_journals": False,
        "rollback_authorized": False,
        "runtime_changes_authorized": False,
        "status": "blocked" if findings else "manual_review_required",
        "findings": findings,
        "note": "No automatic recovery or completion; independent human-controlled transaction required.",
    }
