"""Bounded, fail-closed discovery of interrupted Server Pack finalizations.

The Agent may periodically invoke discovery; discovery never mutates an instance.
Mutating recovery requires a separately wired, explicitly authorized callback,
plus the same per-instance lock used by all runtime operations.
"""
from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any


class FinalizationSchedulerError(RuntimeError):
    pass


def scan_pending_finalizations(
    *,
    state_root: Path,
    agent_id: str,
    lock_instance: Callable[[str], Any],
    read_operation: Callable[[str], Mapping[str, Any] | None],
    dispatch: Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None = None,
    enabled: bool = False,
    max_candidates: int = 4,
) -> list[dict[str, str]]:
    """Read only by default. Optional dispatch runs while instance lock is held.

    Caller must provide lock_instance as a context-manager factory backed by
    runtime_lock.instance_lock. No direct effects on disk are performed here.
    """
    if not agent_id or len(agent_id) > 191 or max_candidates not in range(1, 17):
        raise FinalizationSchedulerError("invalid scheduler configuration")
    root = Path(state_root) / "instance-provisioning"
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise FinalizationSchedulerError("unsafe provisioning directory")
    results: list[dict[str, str]] = []
    # Bound total I/O yet do not let the first few unrelated completed jobs
    # permanently starve an older pending operation.
    candidates = sorted(root.glob("*.result.json"))[:256]
    for path in candidates:
        if len(results) >= max_candidates:
            break
        if path.is_symlink() or not path.is_file():
            results.append({"status": "rejected", "reason": "unsafe_result_path"})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            results.append({"status": "rejected", "reason": "unreadable_result"})
            continue
        if not isinstance(payload, dict):
            continue
        instance_id = str(payload.get("instance_id") or "")
        pid = str(payload.get("provisioning_id") or "")
        if (not instance_id or len(instance_id) > 191
                or not pid or len(pid) > 191
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in instance_id + pid)
                or path.name != pid + ".result.json"):
            results.append({"status": "rejected", "reason": "invalid_identity"})
            continue
        if (payload.get("status") != "running"
                or payload.get("finalization_state") != "pending"
                or payload.get("current_step") != "minecraft_serverpack_finalization"):
            continue
        # Reread under lock to reject races between the scanner and executor.
        with lock_instance(instance_id):
            if path.is_symlink() or not path.is_file():
                results.append({"status": "rejected", "reason": "result_changed"})
                continue
            try:
                fresh = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                results.append({"status": "rejected", "reason": "result_changed"})
                continue
            if not isinstance(fresh, dict) or fresh != payload:
                results.append({"status": "rejected", "reason": "result_changed"})
                continue
            outer = read_operation(instance_id)
            if (not isinstance(outer, Mapping)
                    or outer.get("agent_id") != agent_id
                    or outer.get("instance_id") != instance_id
                    or outer.get("operation") != "minecraft_serverpack_migration"
                    or outer.get("status") != "finalization_pending"):
                results.append({"status": "rejected", "reason": "operation_mismatch"})
                continue
            detail = fresh.get("minecraft_serverpack_migration")
            plan = str(outer.get("migration_plan_sha256") or "")
            if (not isinstance(detail, dict)
                    or len(plan) != 64
                    or any(c not in "0123456789abcdef" for c in plan)
                    or detail.get("migration_plan_sha256") != plan
                    or detail.get("status") != "finalization_pending"):
                results.append({"status": "rejected", "reason": "plan_mismatch"})
                continue
            if enabled and callable(dispatch):
                dispatch(outer, fresh)
                results.append({"status": "dispatched", "instance_id": instance_id})
            else:
                results.append({"status": "pending", "instance_id": instance_id})
    return results
