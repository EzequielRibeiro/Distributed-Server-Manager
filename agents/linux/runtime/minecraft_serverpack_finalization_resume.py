"""Fail-closed recovery of a previously committed Minecraft migration.

Inject only trusted Agent callbacks. Caller holds the per-instance runtime
lock and validates the user's authorized instance. No default service action
or privileged archive is provided by this module.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from minecraft_serverpack_finalization_checkpoint import discover_committed_checkpoint


class ResumeError(RuntimeError):
    pass


def resume_committed_migration(
    *,
    instance_root: Path,
    operation: Mapping[str, Any],
    provisioning: Mapping[str, Any],
    instance_id: str,
    agent_id: str,
    observe_service: Callable[[], str],
    archive_committed: Callable[[], Mapping[str, Any]],
    restore_service: Callable[[str], str],
) -> dict[str, Any]:
    """Resume commit/archival/restart without reinstalling or rolling back.

    Return success evidence ONLY after service state agrees with its original
    availability and archived journal passes durable checksum validation.
    """
    if not isinstance(operation, Mapping) or not isinstance(provisioning, Mapping):
        raise ResumeError("missing operation or provisioning record")
    if (operation.get("instance_id") != instance_id
            or operation.get("agent_id") != agent_id
            or operation.get("operation") != "minecraft_serverpack_migration"
            or operation.get("status") != "finalization_pending"
            or provisioning.get("instance_id") != instance_id
            or provisioning.get("status") != "running"
            or provisioning.get("current_step") != "minecraft_serverpack_finalization"
            or provisioning.get("finalization_state") != "pending"):
        raise ResumeError("finalization identity or state mismatch")
    detail = provisioning.get("minecraft_serverpack_migration")
    if (not isinstance(detail, Mapping)
            or detail.get("status") != "finalization_pending"
            or "committed" not in detail.get("trace", [])):
        raise ResumeError("provisioning lacks committed transaction evidence")
    plan = str(detail.get("migration_plan_sha256") or "")
    loader = str(detail.get("target_loader_version") or "")
    if operation.get("migration_plan_sha256") != plan:
        raise ResumeError("operation fingerprint mismatch")
    committed = detail.get("commit")
    original = (str(committed.get("initial_active_state") or "").lower()
                if isinstance(committed, Mapping) else "")
    if original not in {"active", "inactive"}:
        raise ResumeError("original service state is unavailable")
    if not all(callable(fn) for fn in (observe_service, archive_committed, restore_service)):
        raise ResumeError("recovery callbacks unavailable")

    # History is independently read from the instance state root, never from
    # an untrusted history string in a Controller-supplied payload.
    try:
        checkpoint = discover_committed_checkpoint(
            instance_root, plan_sha256=plan, loader_version=loader)
    except Exception as exc:
        raise ResumeError("committed checkpoint could not be verified") from exc
    observed = observe_service()
    if observed not in {"active", "inactive"}:
        raise ResumeError("service state is unsafe or ambiguous")
    if checkpoint["status"] == "active":
        if observed != "inactive":
            raise ResumeError("service must be stopped before archiving")
        evidence = archive_committed()
        if (not isinstance(evidence, Mapping)
                or evidence.get("status") not in {"archived", "already_archived"}
                or evidence.get("sha256") != checkpoint["sha256"]):
            raise ResumeError("privileged archival evidence differs")
        try:
            checkpoint = discover_committed_checkpoint(
                instance_root, plan_sha256=plan, loader_version=loader)
        except Exception as exc:
            raise ResumeError("archived checkpoint could not be independently verified") from exc
        if checkpoint["status"] != "archived":
            raise ResumeError("archive did not complete")
    else:
        # Do not repeat a privileged archive after the journal has moved.
        # Reconciliation can continue from a verified historical checkpoint.
        evidence = {"status": "already_archived", "sha256": checkpoint["sha256"]}

    observed = observe_service()
    if observed not in {"active", "inactive"}:
        raise ResumeError("service state changed unexpectedly")
    if observed != original:
        if observed != "inactive":
            raise ResumeError("unexpected active service state")
        try:
            restored = restore_service(original)
        except Exception as exc:
            raise ResumeError("service restoration failed; migration remains pending") from exc
        if restored != original or observe_service() != original:
            raise ResumeError("service did not return to its original state")
    return {
        "status": "finalized", "instance_id": instance_id,
        "migration_plan_sha256": plan, "target_loader_version": loader,
        "archive_status": evidence["status"],
        "sha256": checkpoint["sha256"],
        "observed_state": original,
        "rollback_performed": False,
    }
