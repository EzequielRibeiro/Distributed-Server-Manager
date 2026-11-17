"""Read-only proof that a later pre-staging failure hit an older committed journal.

Never completes, recovers, archives or rewrites operations. The proof binds
specific durable historical artifacts; runtime health is a separate gate.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class PreStageCollisionEvidenceError(ValueError):
    pass


def assess_pre_stage_committed_collision(
    *, instance_id: str, agent_id: str,
    previous_request: Mapping[str, Any], previous_result: Mapping[str, Any],
    failed_request: Mapping[str, Any], failed_result: Mapping[str, Any],
    failed_operation: Mapping[str, Any], existing_journal: Mapping[str, Any],
    filesystem_artifacts_absent: bool, game_unit_inactive: bool,
) -> dict[str, Any]:
    """Only classify provenance; success never authorizes operational recovery.

    The caller must supply independently read, immutable/attested records and
    check filesystem artifacts and game-unit state under its instance lock.
    """
    inputs=(previous_request,previous_result,failed_request,failed_result,failed_operation,existing_journal)
    if not instance_id or not agent_id or not all(isinstance(x,Mapping) for x in inputs):
        raise PreStageCollisionEvidenceError("complete trusted provenance required")
    for item in (previous_request, previous_result, failed_request, failed_result, failed_operation):
        if item.get("instance_id")!=instance_id:
            raise PreStageCollisionEvidenceError("instance provenance mismatch")
    for item in (previous_request, failed_request, failed_operation):
        if item.get("agent_id")!=agent_id:
            raise PreStageCollisionEvidenceError("Agent provenance mismatch")
    old=previous_result.get("minecraft_serverpack_migration")
    if (previous_result.get("status")!="completed"
            or not isinstance(old,Mapping) or old.get("status")!="completed"
            or "committed" not in (old.get("trace") or ())):
        raise PreStageCollisionEvidenceError("previous committed migration not proven")
    commit=old.get("commit")
    if (not isinstance(commit,Mapping) or commit.get("status")!="committed"
            or not isinstance(commit.get("journal"),Mapping)
            or dict(commit["journal"])!=dict(existing_journal)
            or existing_journal.get("phase")!="committed"
            or existing_journal.get("kind")!="CapivaraMinecraftServerPackMigrationSwap"
            or old.get("migration_plan_sha256")!=existing_journal.get("migration_plan_sha256")):
        raise PreStageCollisionEvidenceError("previous commit journal identity mismatch")
    prior_selector=previous_request.get("selector")
    failed_selector=failed_request.get("selector")
    if not isinstance(prior_selector,str) or not isinstance(failed_selector,str) or prior_selector==failed_selector:
        raise PreStageCollisionEvidenceError("distinct later migration request not proven")
    if (failed_result.get("status")!="failed"
            or failed_result.get("current_step")!="minecraft_serverpack_migration"
            or failed_operation.get("operation")!="minecraft_serverpack_migration"
            or failed_operation.get("status")!="failed"
            or failed_operation.get("error")!="migration failed and rollback also failed: manual recovery required"
            or failed_result.get("error")!=failed_operation.get("error")):
        raise PreStageCollisionEvidenceError("specific failed migration operation not proven")
    traceback=failed_result.get("traceback")
    if (not isinstance(traceback,str)
            or "RuntimeError: Server Pack migration journal already exists" not in traceback
            or "RuntimeError: committed migration cannot be silently recovered" not in traceback
            or 'callbacks["stage"]' not in traceback
            or 'callbacks["rollback"]' not in traceback
            or 'callbacks["swap"]' in traceback):
        raise PreStageCollisionEvidenceError("pre-staging collision traceback not proven")
    if filesystem_artifacts_absent is not True or game_unit_inactive is not True:
        raise PreStageCollisionEvidenceError("unsafe filesystem artifacts or game service state")
    return {
        "kind":"MinecraftPreStageCommittedCollisionAssessment",
        "instance_id":instance_id,"agent_id":agent_id,
        "classification":"later_pre_stage_collision_with_previous_commit",
        "previous_target_loader_version":old.get("target_loader_version"),
        "failed_request_selector":failed_selector,
        "journal_unchanged_from_previous_commit":True,
        "read_only":True,
        "operation_release_authorized":False,
        "runtime_recovery_authorized":False,
        "new_migration_authorized":False,
        "runtime_healthy_asserted":False,
        "status":"manual_recovery_design_required",
    }
