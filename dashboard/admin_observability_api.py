#!/usr/bin/env python3
"""P8 consolidated administrative observability read model."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from activity_audit_repository import ActivityAuditRepository
from observability_repository import ObservabilityRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def _rows(connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    except Exception:
        return []


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter = Counter(str(row.get(field) or "unknown").strip().lower() for row in rows)
    return dict(sorted(counter.items()))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _operation_safe(row: dict[str, Any]) -> dict[str, Any]:
    request = _json_object(row.get("request_json"))
    result = _json_object(row.get("result_json"))
    return {
        "id": row.get("id"),
        "operation_type": row.get("operation_type"),
        "status": row.get("status"),
        "agent_id": row.get("agent_id") or request.get("agent_id") or result.get("agent_id"),
        "node_id": row.get("node_id"),
        "instance_id": row.get("instance_id"),
        "customer_id": row.get("customer_id") or request.get("customer_id") or result.get("customer_id"),
        "correlation_id": row.get("correlation_id") or request.get("correlation_id") or result.get("correlation_id"),
        "error_code": row.get("error_code"),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


def _alert_safe(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "scope": row.get("scope"),
        "severity": row.get("severity") or row.get("level"),
        "status": row.get("status") or row.get("state"),
        "code": row.get("code") or row.get("rule_id"),
        "agent_id": row.get("agent_id"),
        "instance_id": row.get("instance_id"),
        "correlation_id": row.get("correlation_id"),
        "created_at": row.get("created_at") or row.get("opened_at"),
        "updated_at": row.get("updated_at"),
    }


def _activity_safe(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("activity_id"),
        "actor": row.get("actor_name") or row.get("actor_id"),
        "role": row.get("actor_role"),
        "action": row.get("action"),
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "correlation_id": row.get("correlation_id"),
        "created_at": row.get("occurred_at"),
    }


def consolidated_observability(*, user, backend, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one safe administrative health snapshot without credentials or raw payloads."""
    _require_admin(user)
    values = filters if isinstance(filters, dict) else {}
    agent_id = str(values.get("agent_id") or "").strip() or None
    instance_id = str(values.get("instance_id") or "").strip() or None
    customer_id = str(values.get("customer_id") or "").strip() or None
    region_id = str(values.get("region_id") or "").strip() or None

    with backend.connect() as connection:
        agents = _rows(connection, "SELECT * FROM agents")
        instances = _rows(connection, "SELECT * FROM instances")
        operations = [_operation_safe(row) for row in _rows(connection, "SELECT * FROM operations ORDER BY created_at DESC LIMIT 100")]
        raw_alerts = _rows(connection, "SELECT * FROM alerts ORDER BY updated_at DESC LIMIT 100")

    alerts = [_alert_safe(row) for row in raw_alerts]
    alerts = [row for row in alerts if str(row.get("status") or "").upper() not in {"RESOLVED", "CLOSED"}]
    try:
        activities = [_activity_safe(row) for row in ActivityAuditRepository(backend).search(limit=50)]
    except Exception:
        activities = []

    if agent_id:
        agents = [row for row in agents if str(row.get("id")) == agent_id]
        instances = [row for row in instances if str(row.get("agent_id")) == agent_id]
        operations = [row for row in operations if str(row.get("agent_id")) == agent_id]
        alerts = [row for row in alerts if str(row.get("agent_id")) == agent_id or row.get("agent_id") is None]
    if instance_id:
        instances = [row for row in instances if str(row.get("id")) == instance_id]
        operations = [row for row in operations if str(row.get("instance_id")) == instance_id]
        alerts = [row for row in alerts if str(row.get("instance_id")) == instance_id or row.get("instance_id") is None]
    if customer_id:
        instances = [row for row in instances if str(row.get("customer_id")) == customer_id]
        operations = [row for row in operations if str(row.get("customer_id")) == customer_id]
    # Region is a public P8 filter contract. No private topology is inferred when a source
    # does not currently persist a public Region dimension.
    _ = region_id

    customer_alerts = [row for row in alerts if str(row.get("scope") or "").startswith("customer:")]
    if customer_id:
        customer_alerts = [row for row in customer_alerts if str(row.get("scope")) == f"customer:{customer_id}"]

    repo = ObservabilityRepository(backend)
    repo.initialize()
    metrics = repo.latest(agent_id=agent_id, instance_id=instance_id, limit=500)
    queue_metrics = [row for row in metrics if "queue" in str(row.get("metric_name") or "").lower()]
    stuck_queue_metrics = [row for row in queue_metrics if any(token in str(row.get("metric_name") or "").lower() for token in ("stuck", "oldest", "retry_exhausted"))]

    warning_alerts = [row for row in alerts if str(row.get("severity") or "").upper() == "WARNING"]
    critical_alerts = [row for row in alerts if str(row.get("severity") or "").upper() == "CRITICAL"]
    failed_operations = [row for row in operations if str(row.get("status") or "").lower() == "failed"]
    health = "critical" if critical_alerts or failed_operations or stuck_queue_metrics else "degraded" if warning_alerts or customer_alerts else "healthy"

    return {
        "schema_version": 1,
        "kind": "CapivaraAdministrativeObservability",
        "health": health,
        "filters": {"agent_id": agent_id, "instance_id": instance_id, "customer_id": customer_id, "region_id": region_id},
        "summary": {
            "agents": {"total": len(agents), "by_status": _count_by(agents, "status"), "by_health": _count_by(agents, "health")},
            "instances": {"total": len(instances), "by_status": _count_by(instances, "status")},
            "operations": {"total_recent": len(operations), "by_status": _count_by(operations, "status")},
            "alerts": {"active": len(alerts), "warning": len(warning_alerts), "critical": len(critical_alerts), "customer_problems": len(customer_alerts)},
            "queues": {"metrics": len(queue_metrics), "potentially_stuck": len(stuck_queue_metrics)},
        },
        "recent": {"operations": operations[:25], "alerts": alerts[:25], "activity": activities[:25]},
        "metrics": metrics,
    }


__all__ = ["consolidated_observability"]
