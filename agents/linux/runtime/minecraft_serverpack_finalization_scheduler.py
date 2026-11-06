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
    target_instance_id: str | None = None,
) -> list[dict[str, str]]:
    """Read only by default. Optional dispatch runs while instance lock is held.

    Caller must provide lock_instance as a context-manager factory backed by
    runtime_lock.instance_lock. No direct effects on disk are performed here.
    """
    valid = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not agent_id or len(agent_id) > 191 or max_candidates not in range(1, 17):
        raise FinalizationSchedulerError("invalid scheduler configuration")
    if target_instance_id is not None and (
        not target_instance_id or len(target_instance_id) > 191
        or any(char not in valid for char in target_instance_id)
    ):
        raise FinalizationSchedulerError("invalid target instance")
    root = Path(state_root) / "instance-provisioning"
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise FinalizationSchedulerError("unsafe provisioning directory")
    results: list[dict[str, str]] = []
    # Bound total I/O yet do not let the first few unrelated completed jobs
    # permanently starve an older pending operation.
    candidates = sorted(root.glob("*.result.json"))
    if len(candidates) > 4096:
        raise FinalizationSchedulerError("too many provisioning records for bounded scan")
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
        if target_instance_id is not None and instance_id != target_instance_id:
            continue
        pid = str(payload.get("provisioning_id") or "")
        if (not instance_id or len(instance_id) > 191
                or not pid or len(pid) > 191
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in instance_id + pid)
                or path.name != pid + ".result.json"):
            results.append({"status": "rejected", "reason": "invalid_identity"})
            continue
        pending = (payload.get("status") == "running"
                   and payload.get("finalization_state") == "pending"
                   and payload.get("current_step") == "minecraft_serverpack_finalization")
        detail_preview = payload.get("minecraft_serverpack_migration")
        trace_preview = detail_preview.get("trace") if isinstance(detail_preview, dict) else None
        reconciliable = (payload.get("status") == "completed"
                         and isinstance(detail_preview, dict)
                         and detail_preview.get("status") == "completed"
                         and isinstance(trace_preview, list)
                         and all(isinstance(item, str) for item in trace_preview)
                         and "finalized" in trace_preview)
        if not (pending or reconciliable):
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
            trace = detail.get("trace") if isinstance(detail, dict) else None
            trace_valid = isinstance(trace, list) and all(isinstance(item, str) for item in trace)
            plan = str(outer.get("migration_plan_sha256") or "")
            if (not isinstance(detail, dict)
                    or len(plan) != 64
                    or any(c not in "0123456789abcdef" for c in plan)
                    or detail.get("migration_plan_sha256") != plan
                    or (not pending and not trace_valid)
                    or (detail.get("status") != "finalization_pending" if pending
                        else (detail.get("status") != "completed"
                              or "committed" not in trace
                              or "finalized" not in trace
                              or not isinstance(detail.get("finalization"), dict)
                              or detail["finalization"].get("status") not in {"archived", "already_archived"}))):
                results.append({"status": "rejected", "reason": "plan_mismatch"})
                continue
            if enabled and callable(dispatch):
                performed=dispatch(outer, fresh)
                results.append({"status": "pending" if performed is False else "dispatched",
                                "instance_id": instance_id})
            else:
                results.append({"status": "pending" if pending else "pending_journal_reconciliation",
                                "instance_id": instance_id})
    return results
