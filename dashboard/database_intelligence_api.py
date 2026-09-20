#!/usr/bin/env python3
"""DB1-DB6 administrative Database Intelligence service boundary."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from activity_audit_repository import ActivityAuditRepository
from database_intelligence_repository import DatabaseIntelligenceRepository
from observability_repository import ObservabilityRepository


def _require_manager(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = _require_manager(user)
    if str(actor.get("role") or "").strip().lower() != "admin":
        raise PermissionError("admin access required for database maintenance actions")
    return actor


def _retention_settings() -> dict[str, int]:
    return {
        "retention_days": max(1, min(int(os.environ.get("DSM_OBSERVABILITY_RETENTION_DAYS", "7")), 365)),
        "history_interval_seconds": max(60, min(int(os.environ.get("DSM_OBSERVABILITY_HISTORY_INTERVAL_SECONDS", "300")), 3600)),
        "batch_size": max(100, min(int(os.environ.get("DSM_OBSERVABILITY_RETENTION_BATCH_SIZE", "5000")), 50000)),
        "worker_seconds": max(60, min(int(os.environ.get("DSM_OBSERVABILITY_RETENTION_WORKER_SECONDS", "300")), 3600)),
    }


def retention_status(*, user, backend) -> dict[str, Any]:
    _require_manager(user)
    settings = _retention_settings()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=settings["retention_days"])).isoformat().replace("+00:00", "Z")
    repo = ObservabilityRepository(backend)
    repo.initialize()
    pending = repo.count_before(cutoff)
    return {
        "schema_version": 1,
        "kind": "CapivaraDatabaseRetention",
        **settings,
        "cutoff": cutoff,
        "pending_rows": pending,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
    }


def database_intelligence(*, user, backend, mode: str = "overview", days: int = 90) -> dict[str, Any]:
    _require_manager(user)
    repo = DatabaseIntelligenceRepository(backend)
    repo.initialize()
    normalized = str(mode or "overview").strip().lower()
    if normalized == "health":
        return repo.health()
    if normalized == "storage":
        return repo.storage(limit=100)
    if normalized == "growth":
        return repo.growth(days=days)
    if normalized == "datamine":
        return {"profile": repo.observability_profile(), "indexes": repo.index_efficiency(limit=50)}
    if normalized == "retention":
        return retention_status(user=user, backend=backend)
    if normalized == "insights":
        return {"insights": repo.insights(), "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    if normalized == "capabilities":
        return repo.capabilities()
    if normalized != "overview":
        raise ValueError("unsupported database intelligence mode")
    return {
        "schema_version": 1,
        "kind": "CapivaraDatabaseIntelligence",
        "health": repo.health(),
        "storage": repo.storage(limit=25),
        "growth": repo.growth(days=days),
        "profile": repo.observability_profile(),
        "retention": retention_status(user=user, backend=backend),
        "insights": repo.insights(),
        "capabilities": repo.capabilities(),
    }


def _audit(backend, actor: dict[str, Any], action: str, summary: str, changes: dict[str, Any]) -> None:
    try:
        ActivityAuditRepository(backend).record_action(
            actor_id=str(actor.get("username") or actor.get("id") or "admin"),
            actor_name=str(actor.get("full_name") or actor.get("username") or "admin"),
            actor_role=str(actor.get("role") or "admin"),
            action=action,
            category="database",
            result="success",
            summary=summary,
            target_type="database",
            target_id=str(backend.config.database),
            target_name=str(backend.name),
            changes=changes,
        )
    except Exception:
        pass


def database_maintenance(*, user, backend, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    actor = _require_admin(user)
    values = payload if isinstance(payload, dict) else {}
    normalized = str(action or "").strip().lower()
    intelligence = DatabaseIntelligenceRepository(backend)
    intelligence.initialize()

    if normalized == "snapshot":
        result = intelligence.capture_snapshot()
        _audit(backend, actor, "database.snapshot", "Database intelligence snapshot captured", result)
        return result

    if normalized == "analyze":
        result = intelligence.analyze()
        _audit(backend, actor, "database.analyze", "Database statistics analyzed", result)
        return result

    if normalized in {"retention-preview", "retention-run"}:
        settings = _retention_settings()
        days = max(1, min(int(values.get("retention_days") or settings["retention_days"]), 365))
        batch = max(100, min(int(values.get("batch_size") or settings["batch_size"]), 50000))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        repo = ObservabilityRepository(backend)
        repo.initialize()
        pending = repo.count_before(cutoff)
        deleted = repo.prune_before(cutoff, limit=batch) if normalized == "retention-run" and pending else 0
        result = {
            "action": normalized,
            "cutoff": cutoff,
            "retention_days": days,
            "batch_size": batch,
            "pending_before": pending,
            "deleted": deleted,
            "remaining_estimate": max(0, pending - deleted),
        }
        if normalized == "retention-run":
            _audit(backend, actor, "database.retention", "Observability retention batch executed", result)
        return result

    raise ValueError("unsupported database maintenance action")


__all__ = [
    "database_intelligence",
    "database_maintenance",
    "retention_status",
    "_require_manager",
    "_require_admin",
]
