#!/usr/bin/env python3
"""Final runtime health/state projection for Agent instances."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import instance_runtime
from runtime_operations import read_operation


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def project_instance_health(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = instance_runtime._owned(config, instance_id)
    desired = str(record.get("desired_state") or "unknown")
    observed = str(record.get("observed_state") or "unknown")
    reconcile = str(record.get("reconcile_status") or "unknown")
    last_error = record.get("reconcile_last_error")
    operation = read_operation(instance_id)
    operation_status = str((operation or {}).get("status") or "idle")
    if reconcile == "degraded" or observed in {"failed", "unavailable"}:
        health = "degraded"
    elif operation_status == "failed":
        health = "degraded"
    elif desired in {"running", "stopped"} and observed == desired and reconcile in {"healthy", "unknown"}:
        health = "healthy"
    elif observed in {"starting", "stopping"} or operation_status == "running":
        health = "transitioning"
    else:
        health = "unknown"
    return {
        "schema_version": 1,
        "kind": "CapivaraInstanceRuntimeHealth",
        "instance_id": record["instance_id"],
        "agent_id": record["agent_id"],
        "desired_state": desired,
        "observed_state": observed,
        "reconcile_status": reconcile,
        "health": health,
        "last_error": last_error,
        "last_transition_at": record.get("updated_at"),
        "operation_status": operation_status,
        "operation": (operation or {}).get("operation"),
        "generated_at": _now(),
    }


def health_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for item in instance_runtime.list_instances(config):
        instance_id = str(item.get("instance_id") or "")
        if not instance_id:
            continue
        try:
            values.append(project_instance_health(config, instance_id))
        except Exception as exc:
            values.append({"instance_id": instance_id, "health": "unknown", "error": str(exc)[:2000]})
    return values


__all__ = ["health_inventory", "project_instance_health"]
