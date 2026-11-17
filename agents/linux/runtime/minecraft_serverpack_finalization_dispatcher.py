"""Explicitly authorized, lock-scoped replay of already published completion.

Never retries installation, archives, start/stop, or state recovery. The
scheduler holds runtime_lock.instance_lock across dispatch.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any

from minecraft_serverpack_finalization_bridge import reconcile_published_migration
from provisioning_state import paths
from runtime_operations import _path as operation_path
from instance_runtime import get_instance


class FinalizationDispatchError(RuntimeError):
    pass


def dispatch_published_completion(
    operation: Mapping[str, Any], result: Mapping[str, Any],
    *, agent_id: str, allowed_instance_id: str,
) -> dict[str, Any]:
    """Allowlisted one-instance journal-only reconciliation under caller's lock."""
    if not isinstance(operation, Mapping) or not isinstance(result, Mapping):
        raise FinalizationDispatchError("missing state")
    instance_id = str(operation.get("instance_id") or "")
    if (not allowed_instance_id or instance_id != allowed_instance_id
            or result.get("instance_id") != instance_id
            or operation.get("agent_id") != agent_id):
        raise FinalizationDispatchError("instance not authorized for reconciliation")
    if result.get("status") != "completed":
        # No automatic privileged archive/restart path is enabled by this dispatcher.
        raise FinalizationDispatchError("only previously published success is eligible")
    record = get_instance(instance_id)
    if (not isinstance(record, dict)
            or record.get("instance_id") != instance_id
            or record.get("agent_id") != agent_id
            or str(record.get("game_id") or "").lower() != "minecraft"):
        raise FinalizationDispatchError("untrusted instance registry record")
    instance_root_text = str(record.get("instance_state_root") or "")
    if not instance_root_text:
        raise FinalizationDispatchError("no registered storage root")
    instance_root = Path(instance_root_text)
    if not instance_root.is_absolute() or instance_root.is_symlink() or not instance_root.is_dir():
        raise FinalizationDispatchError("invalid registered storage root")
    working = str(record.get("working_directory") or record.get("files_root") or "")
    if not working or Path(working).resolve() != (instance_root / "runtime").resolve():
        raise FinalizationDispatchError("registered runtime path differs")
    pid = str(result.get("provisioning_id") or "")
    try:
        _, provisioning_path, _ = paths(pid)
    except ValueError as exc:
        raise FinalizationDispatchError("invalid provisioning reference") from exc
    return reconcile_published_migration(
        instance_id=instance_id,
        agent_id=agent_id,
        operation_path=operation_path(instance_id),
        provisioning_path=provisioning_path,
        history_root=instance_root / ".dsm" / "migration-history",
    )
