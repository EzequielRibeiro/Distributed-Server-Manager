#!/usr/bin/env python3
"""Canonical contracts for E2 High Availability & Disaster Recovery."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
HA_MODES = {"manual", "automatic"}
HA_MEMBER_ROLES = {"primary", "standby", "witness"}
HA_MEMBER_STATES = {"unknown", "healthy", "degraded", "offline", "fenced", "disabled"}
FAILOVER_STATES = {"requested", "validating", "fencing", "promoting", "converging", "completed", "failed", "rolled_back"}
RECOVERY_POINT_STATES = {"creating", "ready", "invalid", "expired"}


class HADisasterRecoveryValidationError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise HADisasterRecoveryValidationError(f"invalid {field}")
    return text


@dataclass(frozen=True)
class HACluster:
    cluster_id: str
    name: str
    mode: str = "manual"
    rpo_seconds: int = 300
    rto_seconds: int = 900
    quorum_size: int = 2
    auto_failback: bool = False

    def normalized(self) -> dict[str, Any]:
        cluster_id = validate_id(self.cluster_id, "cluster_id")
        name = str(self.name or "").strip()
        if not name:
            raise HADisasterRecoveryValidationError("name is required")
        mode = str(self.mode or "").strip().lower()
        if mode not in HA_MODES:
            raise HADisasterRecoveryValidationError("invalid HA mode")
        rpo = int(self.rpo_seconds)
        rto = int(self.rto_seconds)
        quorum = int(self.quorum_size)
        if rpo < 0 or rto <= 0:
            raise HADisasterRecoveryValidationError("invalid RPO/RTO")
        if quorum < 1:
            raise HADisasterRecoveryValidationError("quorum_size must be positive")
        return {
            "cluster_id": cluster_id,
            "name": name,
            "mode": mode,
            "rpo_seconds": rpo,
            "rto_seconds": rto,
            "quorum_size": quorum,
            "auto_failback": bool(self.auto_failback),
        }


@dataclass(frozen=True)
class HAClusterMember:
    cluster_id: str
    controller_id: str
    role: str
    state: str = "unknown"
    priority: int = 100

    def normalized(self) -> dict[str, Any]:
        cluster_id = validate_id(self.cluster_id, "cluster_id")
        controller_id = validate_id(self.controller_id, "controller_id")
        role = str(self.role or "").strip().lower()
        state = str(self.state or "").strip().lower()
        priority = int(self.priority)
        if role not in HA_MEMBER_ROLES:
            raise HADisasterRecoveryValidationError("invalid HA member role")
        if state not in HA_MEMBER_STATES:
            raise HADisasterRecoveryValidationError("invalid HA member state")
        if priority < 0:
            raise HADisasterRecoveryValidationError("priority must be non-negative")
        return {
            "cluster_id": cluster_id,
            "controller_id": controller_id,
            "role": role,
            "state": state,
            "priority": priority,
        }


def next_fencing_epoch(current_epoch: int | None) -> int:
    value = int(current_epoch or 0)
    if value < 0:
        raise HADisasterRecoveryValidationError("fencing epoch cannot be negative")
    return value + 1


def failover_operation_id(cluster_id: str) -> str:
    validate_id(cluster_id, "cluster_id")
    return "hafo_" + uuid.uuid4().hex


def recovery_point_id(cluster_id: str) -> str:
    validate_id(cluster_id, "cluster_id")
    return "harp_" + uuid.uuid4().hex


def select_failover_candidate(members: list[dict[str, Any]], *, exclude_controller_id: str | None = None) -> dict[str, Any] | None:
    candidates = []
    for raw in members:
        member = HAClusterMember(
            cluster_id=raw.get("cluster_id"),
            controller_id=raw.get("controller_id"),
            role=raw.get("role"),
            state=raw.get("state", "unknown"),
            priority=raw.get("priority", 100),
        ).normalized()
        if member["controller_id"] == exclude_controller_id:
            continue
        if member["role"] != "standby" or member["state"] not in {"healthy", "degraded"}:
            continue
        candidates.append(member)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (0 if item["state"] == "healthy" else 1, item["priority"], item["controller_id"]))
    return candidates[0]


def quorum_satisfied(members: list[dict[str, Any]], quorum_size: int) -> bool:
    votes = 0
    for raw in members:
        state = str(raw.get("state") or "unknown").lower()
        role = str(raw.get("role") or "").lower()
        if role in HA_MEMBER_ROLES and state in {"healthy", "degraded"}:
            votes += 1
    return votes >= int(quorum_size)
