"""Fail-closed reconciliation for durable Minecraft Server Pack finalization.

Runs only with an independently acquired per-instance lock. The normal Agent
does not invoke this module automatically until an isolated E2E approves the
integration. Callers inject Agent-owned, revalidated persistence and effects.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class FinalizationReconciliationError(RuntimeError):
    pass


def reconcile_finalization(
    *, operation: Mapping[str, Any], result: Mapping[str, Any],
    instance_id: str, agent_id: str,
    complete_operation: Callable[[Mapping[str, Any]], None],
    run_recovery: Callable[[], Mapping[str, Any]],
    complete_provisioning: Callable[[Mapping[str, Any]], None],
) -> dict[str, Any]:
    """Reconcile two durable records under lock; never rerun a completed action.

    After recovery, publish provisioning success *first*, then mark the outer
    operation complete. Replays after a crash between these writes only finish
    the outer journal. No callback performs speculative rollback.
    """
    if not isinstance(operation, Mapping) or not isinstance(result, Mapping):
        raise FinalizationReconciliationError("missing durable records")
    if (operation.get("instance_id") != instance_id
        or operation.get("agent_id") != agent_id
        or operation.get("operation") != "minecraft_serverpack_migration"):
        raise FinalizationReconciliationError("operation identity does not match")
    if result.get("instance_id") != instance_id or not str(result.get("provisioning_id") or ""):
        raise FinalizationReconciliationError("provisioning identity does not match")
    plan = str(operation.get("migration_plan_sha256") or "").lower()
    if (len(plan) != 64 or any(c not in "0123456789abcdef" for c in plan)):
        raise FinalizationReconciliationError("operation lacks migration fingerprint")
    detail = result.get("minecraft_serverpack_migration")
    if not isinstance(detail, Mapping) or detail.get("migration_plan_sha256") != plan:
        raise FinalizationReconciliationError("provisioning migration fingerprint mismatch")
    op_status = str(operation.get("status") or "")
    res_status = str(result.get("status") or "")
    if res_status == "completed":
        evidence = result.get("minecraft_serverpack_migration")
        if (not isinstance(evidence, Mapping)
            or evidence.get("status") != "completed"
            or "committed" not in evidence.get("trace", [])
            or "finalized" not in evidence.get("trace", [])
            or not isinstance(evidence.get("finalization"), Mapping)
            or evidence["finalization"].get("status") not in {"archived", "already_archived"}):
            raise FinalizationReconciliationError("unverified completed result")
        if op_status == "completed":
            return {"status": "already_completed"}
        if op_status != "finalization_pending":
            raise FinalizationReconciliationError("unsafe operation state for completion")
        complete_operation(operation)
        return {"status": "operation_reconciled"}
    if op_status != "finalization_pending" or res_status != "running":
        raise FinalizationReconciliationError("no eligible pending finalization")
    if (result.get("current_step") != "minecraft_serverpack_finalization"
        or result.get("finalization_state") != "pending"):
        raise FinalizationReconciliationError("finalization state is not pending")
    if not all(callable(x) for x in (complete_operation, run_recovery, complete_provisioning)):
        raise FinalizationReconciliationError("required callback missing")
    outcome = run_recovery()
    if (not isinstance(outcome, Mapping)
        or outcome.get("status") not in {"finalized", "restart_recovered"}
        or outcome.get("instance_id") != instance_id
        or outcome.get("migration_plan_sha256") != plan):
        raise FinalizationReconciliationError("recovery has no verified success evidence")
    # On crash here, the outer record remains pending; retry must be verified
    # idempotent by the independent recovery primitive.
    complete_provisioning(outcome)
    # On crash here, next cycle recognizes the completed result and only
    # releases the outer journal barrier.
    complete_operation(operation)
    return {"status": "completed", "recovery_status": outcome["status"]}
