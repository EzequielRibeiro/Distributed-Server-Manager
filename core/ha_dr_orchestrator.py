#!/usr/bin/env python3
"""Operational orchestration for E2 HA/DR.

This layer deliberately separates failure detection, fencing, promotion and
failback from persistence. External side effects are injected as callbacks so
platform-specific database/VIP mechanisms stay outside the generic control
plane.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def member_is_stale(member: Mapping[str, Any], *, now: datetime | None = None, timeout_seconds: int = 45) -> bool:
    now = now or datetime.now(timezone.utc)
    seen = _parse_time(member.get("last_seen_at"))
    if seen is None:
        return True
    return (now - seen).total_seconds() > max(5, int(timeout_seconds))


@dataclass
class FailoverHooks:
    fence: Callable[[str, int], bool]
    promote: Callable[[str, int], bool]
    converge: Callable[[str, int], bool]
    demote: Callable[[str, int], bool] | None = None
    restore: Callable[[Mapping[str, Any]], bool] | None = None


class HADROrchestrator:
    def __init__(self, repository: Any, hooks: FailoverHooks):
        self.repository = repository
        self.hooks = hooks

    def detect_primary_failure(self, cluster_id: str, *, timeout_seconds: int = 45) -> dict[str, Any]:
        status = self.repository.cluster_status(cluster_id)
        primary = status.get("primary")
        failed = primary is None or str(primary.get("state")) in {"offline", "fenced", "disabled"}
        if primary and not failed:
            failed = member_is_stale(primary, timeout_seconds=timeout_seconds)
        return {"cluster_id": cluster_id, "failed": failed, "primary": primary, "quorum": bool(status.get("quorum")), "candidate": status.get("candidate")}

    def automatic_failover(self, cluster_id: str, *, timeout_seconds: int = 45, requested_by: str = "ha-monitor") -> dict[str, Any] | None:
        detected = self.detect_primary_failure(cluster_id, timeout_seconds=timeout_seconds)
        if not detected["failed"]:
            return None
        if not detected["quorum"]:
            raise RuntimeError("primary failure detected but quorum is unavailable; refusing promotion")
        operation = self.repository.request_failover(cluster_id, reason="primary failure detected", requested_by=requested_by, automatic=True)
        return self.execute_failover(operation["operation_id"])

    def execute_failover(self, operation_id: str) -> dict[str, Any]:
        op = self.repository.get_failover_operation(operation_id)
        source = op.get("source_controller_id")
        target = op.get("target_controller_id")
        epoch = int(op.get("fencing_epoch") or 0)
        if not target or epoch <= 0:
            raise RuntimeError("invalid failover operation")
        self.repository.transition_failover(operation_id, "validating", message="quorum and target validated")
        if source:
            self.repository.transition_failover(operation_id, "fencing", message="fencing former primary")
            if not self.hooks.fence(source, epoch):
                self.repository.transition_failover(operation_id, "failed", message="fencing failed; promotion refused")
                raise RuntimeError("fencing failed; promotion refused")
            self.repository.mark_member_state(op["cluster_id"], source, "fenced")
        self.repository.transition_failover(operation_id, "promoting", message="promoting standby")
        if not self.hooks.promote(target, epoch):
            self.repository.transition_failover(operation_id, "failed", message="standby promotion failed")
            raise RuntimeError("standby promotion failed")
        self.repository.promote_member(op["cluster_id"], target, fencing_epoch=epoch)
        self.repository.transition_failover(operation_id, "converging", message="converging control-plane services")
        if not self.hooks.converge(target, epoch):
            self.repository.transition_failover(operation_id, "failed", message="post-promotion convergence failed")
            raise RuntimeError("post-promotion convergence failed")
        return self.repository.transition_failover(operation_id, "completed", message="failover completed")

    def failback(self, cluster_id: str, target_controller_id: str, *, requested_by: str = "operator") -> dict[str, Any]:
        operation = self.repository.request_failover(cluster_id, target_controller_id=target_controller_id, reason="controlled failback", requested_by=requested_by, automatic=False)
        return self.execute_failover(operation["operation_id"])

    def restore_recovery_point(self, recovery_point: Mapping[str, Any]) -> bool:
        if str(recovery_point.get("state")) != "ready":
            raise RuntimeError("recovery point is not ready")
        if self.hooks.restore is None:
            raise RuntimeError("restore hook is not configured")
        return bool(self.hooks.restore(recovery_point))
