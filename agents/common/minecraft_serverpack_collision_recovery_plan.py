"""Pure recovery plan for a historical pre-stage migration collision.

Never modify a game, journal or lock. Fail closed until independent runtime
integrity is attested. Previous committed state is not itself evidence that
current runtime remains intact.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

class CollisionRecoveryPlanError(ValueError):
    pass


def build_collision_recovery_plan(*, collision: Mapping[str,Any],
    current_operation: Mapping[str,Any], current_swap_journal: Mapping[str,Any],
    prior_completed_journal: Mapping[str,Any],
    original_rollback_digest_matches: bool, active_managed_digest_matches: bool,
    loader_verified: bool, content_archive_verified: bool,
    world_backup_verified: bool, game_unit_inactive: bool,
    exclusive_instance_lock_held: bool) -> dict[str,Any]:
    """Return a non-executable decision with explicit blockers.

    The caller is responsible for independently recomputing every attestation;
    no Boolean claim from an untrusted customer payload may be used.
    """
    if not all(isinstance(v,Mapping) for v in (collision,current_operation,current_swap_journal,prior_completed_journal)):
        raise CollisionRecoveryPlanError("trusted recovery evidence is required")
    if (collision.get("classification")!="later_pre_stage_collision_with_previous_commit"
        or collision.get("status")!="manual_recovery_design_required"
        or collision.get("journal_unchanged_from_previous_commit") is not True
        or collision.get("read_only") is not True
        or collision.get("operation_release_authorized") is not False
        or current_operation.get("operation")!="minecraft_serverpack_migration"
        or current_operation.get("status")!="failed"
        or current_operation.get("instance_id")!=collision.get("instance_id")
        or current_operation.get("agent_id")!=collision.get("agent_id")
        or current_swap_journal.get("phase")!="committed"
        or dict(current_swap_journal)!=dict(prior_completed_journal)):
        raise CollisionRecoveryPlanError("collision and original commit identity mismatch")
    checks={
        "exclusive_instance_lock_held":exclusive_instance_lock_held,
        "game_unit_inactive":game_unit_inactive,
        "original_rollback_digest_matches":original_rollback_digest_matches,
        "active_managed_digest_matches":active_managed_digest_matches,
        "loader_verified":loader_verified,
        "content_archive_verified":content_archive_verified,
        "world_backup_verified":world_backup_verified,
    }
    blockers=[key for key,value in checks.items() if value is not True]
    return {
        "kind":"MinecraftServerPackCollisionRecoveryPlan",
        "instance_id":collision["instance_id"],"agent_id":collision["agent_id"],
        "status":"blocked" if blockers else "ready_for_supervised_implementation",
        "blockers":blockers,
        "read_only":True,"operation_modified":False,
        "journal_modified":False,"world_modified":False,
        "execution_authorized":False,
        "required_effects_when_implemented":[
            "persist_original_failed_operation_as_immutable_audit",
            "atomically_reclassify_only_latest_failed_outer_operation",
            "preserve_prior_committed_journal_and_both_runtime_trees",
            "keep_new_migration_blocked_until_safe_archival",
        ],
    }
