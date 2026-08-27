#!/usr/bin/env python3
"""P8 consolidated administrative observability read model."""

from __future__ import annotations

from collections import Counter
from typing import Any

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


def consolidated_observability(*, user, backend, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one safe administrative health snapshot without exposing credentials/secrets."""
    _require_admin(user)
    values = filters if isinstance(filters, dict) else {}
    agent_id = str(values.get("agent_id") or "").strip() or None
    instance_id = str(values.get("instance_id") or "").strip() or None
    customer_id = str(values.get("customer_id") or "").strip() or None
    region_id = str(values.get("region_id") or "").strip() or None

    with backend.connect() as connection:
        agents = _rows(connection, "SELECT id,status,health,last_seen_at FROM agents")
        instances = _rows(connection, "SELECT id,agent_id,customer_id,status FROM instances")
        operations = _rows(connection, "SELECT id,operation_type,status,agent_id,instance_id,customer_id,correlation_id,created_at,updated_at FROM operations ORDER BY created_at DESC LIMIT 100")
        alerts = _rows(connection, "SELECT id,scope,severity,status,code,correlation_id,created_at,updated_at FROM alerts WHERE status NOT IN ('resolved','closed') ORDER BY created_at DESC LIMIT 100")
        activities = _rows(connection, "SELECT id,actor,role,action,target_type,target_id,correlation_id,created_at FROM activity_log ORDER BY created_at DESC LIMIT 50")
        customer_alerts = [row for row in alerts if str(row.get("scope") or "").startswith("customer:")]

    if agent_id:
        agents = [row for row in agents if str(row.get("id")) == agent_id]
        instances = [row for row in instances if str(row.get("agent_id")) == agent_id]
        operations = [row for row in operations if str(row.get("agent_id")) == agent_id]
    if instance_id:
        instances = [row for row in instances if str(row.get("id")) == instance_id]
        operations = [row for row in operations if str(row.get("instance_id")) == instance_id]
    if customer_id:
        instances = [row for row in instances if str(row.get("customer_id")) == customer_id]
        operations = [row for row in operations if str(row.get("customer_id")) == customer_id]
        customer_alerts = [row for row in customer_alerts if str(row.get("scope")) == f"customer:{customer_id}"]
    # Region is intentionally accepted as a public filter contract. Sources that do not
    # expose Region in their current schema are left unfiltered rather than inferring private topology.
    _ = region_id

    repo = ObservabilityRepository(backend)
    repo.initialize()
    metrics = repo.latest(agent_id=agent_id, instance_id=instance_id, limit=500)

    queue_metrics = [row for row in metrics if "queue" in str(row.get("metric_name") or "").lower()]
    stuck_queue_metrics = [row for row in queue_metrics if any(token in str(row.get("metric_name") or "").lower() for token in ("stuck", "oldest", "retry_exhausted"))]

    warning_alerts = [row for row in alerts if str(row.get("severity") or "").lower() == "warning"]
    critical_alerts = [row for row in alerts if str(row.get("severity") or "").lower() == "critical"]
    failed_operations = [row for row in operations if str(row.get("status") or "").lower() == "failed"]

    health = "healthy"
    if critical_alerts or failed_operations or stuck_queue_metrics:
        health = "critical"
    elif warning_alerts or customer_alerts:
        health = "degraded"

    return {
        "schema_version": 1,
        "kind": "CapivaraAdministrativeObservability",
        "health": health,
        "filters": {
            "agent_id": agent_id,
            "instance_id": instance_id,
            "customer_id": customer_id,
            "region_id": region_id,
        },
        "summary": {
            "agents": {"total": len(agents), "by_status": _count_by(agents, "status"), "by_health": _count_by(agents, "health")},
            "instances": {"total": len(instances), "by_status": _count_by(instances, "status")},
            "operations": {"total_recent": len(operations), "by_status": _count_by(operations, "status")},
            "alerts": {"active": len(alerts), "warning": len(warning_alerts), "critical": len(critical_alerts), "customer_problems": len(customer_alerts)},
            "queues": {"metrics": len(queue_metrics), "potentially_stuck": len(stuck_queue_metrics)},
        },
        "recent": {
            "operations": operations[:25],
            "alerts": alerts[:25],
            "activity": activities[:25],
        },
        "metrics": metrics,
    }


__all__ = ["consolidated_observability"]
