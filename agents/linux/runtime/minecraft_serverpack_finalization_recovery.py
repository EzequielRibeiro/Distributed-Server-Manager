"""Isolated proof-of-concept: retry only a previously committed finalization.

No direct deletion, no restart, no automatic scheduling. The caller must
acquire the per-instance lock and supply verified agent-owned evidence.
"""
from __future__ import annotations
from collections.abc import Mapping, Callable
from typing import Any


class FinalizationRecoveryError(RuntimeError):
    pass


def retry_committed_finalization(
    *, operation: Mapping[str, Any], provisioning: Mapping[str, Any],
    swap_journal: Mapping[str, Any], instance_id: str, agent_id: str,
    service_inactive: bool, archive: Callable[[], Mapping[str, Any]]
) -> dict[str, Any]:
    """Caller supplies snapshots re-read under its exclusive instance lock."""
    if not isinstance(operation, Mapping) or not isinstance(provisioning, Mapping) or not isinstance(swap_journal, Mapping):
        raise FinalizationRecoveryError("missing durable evidence")
    if (operation.get("instance_id") != instance_id
        or operation.get("agent_id") != agent_id
        or operation.get("operation") != "minecraft_serverpack_migration"
        or operation.get("status") != "finalization_pending"):
        raise FinalizationRecoveryError("operation is not a matching pending finalization")
    if (provisioning.get("instance_id") != instance_id
        or provisioning.get("status") != "running"
        or provisioning.get("current_step") != "minecraft_serverpack_finalization"
        or provisioning.get("finalization_state") != "pending"):
        raise FinalizationRecoveryError("provisioning does not match pending finalization")
    detail=provisioning.get("minecraft_serverpack_migration")
    if (not isinstance(detail, Mapping)
        or detail.get("status") != "finalization_pending"
        or "committed" not in detail.get("trace", [])
        or detail.get("migration_plan_sha256") != swap_journal.get("migration_plan_sha256")
        or detail.get("target_loader_version") != swap_journal.get("target_loader_version")
        or swap_journal.get("phase") != "committed"):
        raise FinalizationRecoveryError("committed migration evidence differs from pending operation")
    if service_inactive is not True:
        raise FinalizationRecoveryError("instance must be confirmed inactive before archive")
    if not callable(archive):
        raise FinalizationRecoveryError("privileged archive callback unavailable")
    outcome=archive()
    if not isinstance(outcome, Mapping) or outcome.get("status") not in {"archived","already_archived"}:
        raise FinalizationRecoveryError("archive did not confirm durable completion")
    return {"status":"finalized","instance_id":instance_id,
            "archive_status":outcome["status"],
            "migration_plan_sha256":swap_journal["migration_plan_sha256"]}



def retry_archived_restart(
    *, operation: Mapping[str, Any], provisioning: Mapping[str, Any],
    archived_journal: Mapping[str, Any], instance_id: str, agent_id: str,
    observed_inactive: bool, restart: Callable[[], str],
) -> dict[str, Any]:
    """Resume only the original availability state after a verified archive.

    Snapshots and archival SHA must be independently revalidated under the
    exclusive instance lock before calling this function. No rollback occurs.
    """
    if not all(isinstance(value, Mapping) for value in (operation, provisioning, archived_journal)):
        raise FinalizationRecoveryError("missing persisted restart evidence")
    if (operation.get("instance_id") != instance_id
        or operation.get("agent_id") != agent_id
        or operation.get("operation") != "minecraft_serverpack_migration"
        or operation.get("status") != "finalization_pending"
        or operation.get("finalization_phase") != "restart_pending"):
        raise FinalizationRecoveryError("operation does not match pending restart")
    if (provisioning.get("instance_id") != instance_id
        or provisioning.get("status") != "running"
        or provisioning.get("current_step") != "minecraft_serverpack_finalization"
        or provisioning.get("finalization_state") != "pending"):
        raise FinalizationRecoveryError("provisioning does not match pending restart")
    detail = provisioning.get("minecraft_serverpack_migration")
    if not isinstance(detail, Mapping) or detail.get("status") != "finalization_pending":
        raise FinalizationRecoveryError("missing finalization result")
    final = detail.get("finalization")
    if (not isinstance(final, Mapping)
        or final.get("status") != "restart_pending"
        or final.get("archive_status") not in {"archived", "already_archived"}
        or archived_journal.get("phase") != "committed"
        or archived_journal.get("migration_plan_sha256") != detail.get("migration_plan_sha256")
        or archived_journal.get("target_loader_version") != detail.get("target_loader_version")
        or "committed" not in detail.get("trace", [])):
        raise FinalizationRecoveryError("archived journal differs from committed checkpoint")
    committed = detail.get("commit")
    original = str((committed or {}).get("initial_active_state") or "").lower() if isinstance(committed, Mapping) else ""
    if original not in {"active", "inactive"}:
        raise FinalizationRecoveryError("original service state is unknown")
    if observed_inactive is not True:
        raise FinalizationRecoveryError("instance state is ambiguous: require manual review")
    if not callable(restart):
        raise FinalizationRecoveryError("restart callback unavailable")
    try:
        state = restart()
    except Exception as exc:
        raise FinalizationRecoveryError("restart failed; archive and runtime remain preserved") from exc
    if state != original:
        raise FinalizationRecoveryError("post-restart state differs from original availability")
    return {"status": "restart_recovered", "instance_id": instance_id,
            "observed_state": state, "rollback_performed": False}
