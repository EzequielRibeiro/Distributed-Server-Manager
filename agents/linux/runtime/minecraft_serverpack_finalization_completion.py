"""Explicitly supervised finalization using real checkpoints and two journals.

Caller MUST own the per-instance runtime lock. Privileged archive/service
callbacks are injected; no default effects, scheduler or auto-restart.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from minecraft_serverpack_finalization_coordinator import reconcile_finalization
from minecraft_serverpack_finalization_resume import resume_committed_migration


class CompletionError(RuntimeError):
    pass


def finish_pending_migration(
    *,
    instance_id: str,
    agent_id: str,
    instance_root: Path,
    operation: Mapping[str, Any],
    provisioning: Mapping[str, Any],
    verify_backup: Callable[[Mapping[str, Any]], bool],
    observe_service: Callable[[], str],
    archive_committed: Callable[[], Mapping[str, Any]],
    restore_service: Callable[[str], str],
    write_provisioning: Callable[[Mapping[str, Any]], None],
    write_operation: Callable[[Mapping[str, Any]], None],
) -> dict[str, Any]:
    """Recover, durably publish success, then release operation barrier.

    Never publish success if verification, archive or restart fails. Callback
    errors leave the outer operation pending; retries must re-read disk state.
    """
    if not isinstance(provisioning, Mapping) or not isinstance(operation, Mapping):
        raise CompletionError("state evidence missing")
    detail = provisioning.get("minecraft_serverpack_migration")
    if not isinstance(detail, Mapping) or not isinstance(detail.get("backup"), Mapping):
        raise CompletionError("retained backup evidence missing")
    if not callable(verify_backup) or verify_backup(detail["backup"]) is not True:
        raise CompletionError("backup could not be independently verified")
    if not all(callable(fn) for fn in (
        observe_service, archive_committed, restore_service, write_provisioning, write_operation
    )):
        raise CompletionError("trusted callback missing")

    def recovery() -> dict[str, Any]:
        return resume_committed_migration(
            instance_root=instance_root,
            operation=operation, provisioning=provisioning,
            instance_id=instance_id, agent_id=agent_id,
            observe_service=observe_service,
            archive_committed=archive_committed,
            restore_service=restore_service,
        )

    def publish(outcome: Mapping[str, Any]) -> None:
        observed = "running" if outcome["observed_state"] == "active" else "stopped"
        updated_detail = dict(detail)
        updated_detail["status"] = "completed"
        updated_detail["trace"] = [*[
            x for x in detail.get("trace", []) if x not in ("finalization_pending", "restart_pending")
        ], "finalized"]
        updated_detail["finalization"] = {
            "status": outcome["archive_status"],
            "sha256": outcome["sha256"],
            "observed_state": observed,
        }
        updated = dict(provisioning)
        updated.update({
            "status": "completed",
            "current_step": "completed",
            "progress": 100,
            "desired_state": observed,
            "observed_state": observed,
            "minecraft_serverpack_migration": updated_detail,
        })
        updated.pop("finalization_state", None)
        updated.pop("recovery_required", None)
        write_provisioning(updated)

    def complete_outer(value: Mapping[str, Any]) -> None:
        updated = dict(value)
        updated["status"] = "completed"
        updated["finalization_reconciled"] = True
        write_operation(updated)

    return reconcile_finalization(
        operation=operation, result=provisioning,
        instance_id=instance_id, agent_id=agent_id,
        run_recovery=recovery, complete_provisioning=publish,
        complete_operation=complete_outer,
    )
