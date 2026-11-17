"""Supervised Agent callback adapter for recovering committed Server Packs.

Never scheduled automatically. Must be called with the exclusive instance
runtime lock already held and explicit Agent-scoped authorization.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from adapters import resolve_adapter
from minecraft_serverpack_finalization_completion import finish_pending_migration
from minecraft_serverpack_finalization_dispatcher import FinalizationDispatchError
from minecraft_serverpack_migration_provisioning import (
    _attest_retained_backup, _readiness_log_baseline, _wait_for_done,
    _feature_for_request,
)
from privileged_materialization import minecraft_serverpack_swap_phase
from provisioning_state import paths
from runtime_operations import _path as operation_path
from minecraft_serverpack_finalization_bridge import _durable_completed_operation, _safe_file
from instance_runtime import get_instance


def recover_pending_operational(
    *,
    config: Mapping[str, Any],
    operation: Mapping[str, Any],
    provisioning: Mapping[str, Any],
    allowed_instance_id: str,
) -> dict[str, Any]:
    """Recover only this allowlisted Minecraft Java NeoForge instance.

    The Agent caller owns the instance_lock across this entire call. The
    callbacks use established privileged helper and readiness gate.
    """
    instance_id = str(operation.get("instance_id") or "")
    agent_id = str(config.get("agent_id") or "")
    if (not allowed_instance_id or allowed_instance_id != instance_id
        or operation.get("agent_id") != agent_id
        or provisioning.get("instance_id") != instance_id
        or provisioning.get("status") != "running"):
        raise FinalizationDispatchError("recovery not authorized")
    record = get_instance(instance_id)
    if (not isinstance(record, dict) or record.get("agent_id") != agent_id
        or record.get("instance_id") != instance_id
        or str(record.get("game_id") or "").lower() != "minecraft"
        or str(record.get("environment_id") or "").lower() != "minecraft.java.neoforge"):
        raise FinalizationDispatchError("registered Minecraft NeoForge instance not verified")
    root = Path(str(record.get("instance_state_root") or ""))
    working = Path(str(record.get("working_directory") or record.get("files_root") or ""))
    if (not root.is_absolute() or not working.is_absolute()
        or root.is_symlink() or not root.is_dir()
        or working.is_symlink() or not working.is_dir()
        or working.resolve() != (root / "runtime").resolve()):
        raise FinalizationDispatchError("registered runtime storage does not match")
    adapter = resolve_adapter(record)
    if getattr(adapter, "name", "") != "systemd":
        raise FinalizationDispatchError("recovery requires systemd-owned runtime")
    _, result_path, _ = paths(str(provisioning.get("provisioning_id") or ""))
    op_path = operation_path(instance_id)
    # The scanner already read under lock; here independently reread the
    # same trusted files before invoking a privileged operation.
    if _safe_file(result_path) != provisioning or _safe_file(op_path) != operation:
        raise FinalizationDispatchError("durable records changed before recovery")

    def verify_backup(data: Mapping[str, Any]) -> bool:
        actual = _attest_retained_backup(data.get("backup_id"),instance_id)
        return (actual.get("integrity_verified") is True
                and actual.get("sha256") == data.get("sha256")
                and actual.get("size_bytes") == data.get("size_bytes"))

    def observe() -> str:
        status = adapter.status(record)
        if not isinstance(status, dict) or not status.get("available"):
            return "unknown"
        return str(status.get("active_state") or "unknown")

    def archive() -> Mapping[str, Any]:
        # The privileged materializer independently validates instance and
        # ownership. Never use paths supplied by the provision payload.
        return minecraft_serverpack_swap_phase(dict(config),record,"archive-committed")

    def restore(state: str) -> str:
        if state == "inactive":
            return observe()
        if state != "active":
            raise FinalizationDispatchError("invalid requested service state")
        baseline = _readiness_log_baseline(working)
        adapter.start(record)
        if not _wait_for_done(record,adapter,baseline=baseline):
            raise FinalizationDispatchError("NeoForge readiness gate failed")
        return observe()

    def publish(value: Mapping[str, Any]) -> None:
        if _safe_file(result_path) != provisioning:
            raise FinalizationDispatchError("provisioning changed during recovery")
        # fsync both journal content and parent directory before releasing
        # the separate operation barrier.
        _durable_completed_operation(result_path,dict(value))

    def finish_outer(value: Mapping[str, Any]) -> None:
        if _safe_file(op_path) != operation:
            raise FinalizationDispatchError("operation changed during recovery")
        # Reuses the fsync-backed, ownership-preserving writer.
        _durable_completed_operation(op_path,dict(value))

    return finish_pending_migration(
        instance_id=instance_id,agent_id=agent_id,instance_root=root,
        operation=operation,provisioning=provisioning,
        verify_backup=verify_backup,observe_service=observe,
        archive_committed=archive,restore_service=restore,
        write_provisioning=publish,write_operation=finish_outer,
    )


def recovery_feature_allowed(instance_id: str, agent_id: str) -> bool:
    """Use existing Agent-side migration policy, never bypass it."""
    return _feature_for_request({"instance_id":instance_id,"agent_id":agent_id})["allowed"] is True
