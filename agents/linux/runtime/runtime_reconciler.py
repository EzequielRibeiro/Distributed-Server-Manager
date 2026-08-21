#!/usr/bin/env python3
"""Continuous desired/observed reconciliation and safe recovery for Agent runtimes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import instance_runtime
import privileged_materialization
import runtime_materialization
from adapters import resolve_adapter
from materializers import resolve_materializer
from runtime_events import emit_runtime_event
from runtime_spec import validate_runtime_spec

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_BASE_BACKOFF_SECONDS = 15
DEFAULT_MAX_BACKOFF_SECONDS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _settings(config: dict[str, Any]) -> tuple[int, int, int]:
    threshold = max(1, int(config.get("reconcile_failure_threshold", DEFAULT_FAILURE_THRESHOLD)))
    base = max(1, int(config.get("reconcile_base_backoff_seconds", DEFAULT_BASE_BACKOFF_SECONDS)))
    maximum = max(base, int(config.get("reconcile_max_backoff_seconds", DEFAULT_MAX_BACKOFF_SECONDS)))
    return threshold, base, maximum


def _event(event_type: str, record: dict[str, Any], data: dict[str, Any] | None = None) -> None:
    emit_runtime_event(
        Path(instance_runtime.STATE_DIR),
        event_type,
        instance_id=str(record["instance_id"]),
        agent_id=str(record["agent_id"]),
        data=dict(data or {}),
    )


def _save(record: dict[str, Any], *, status: str, observed_state: str | None = None, drift: str | None = None,
          retry_count: int = 0, next_retry_at: str | None = None, error: str | None = None,
          recovery_action: str | None = None) -> dict[str, Any]:
    body = dict(record)
    if observed_state is not None:
        body["observed_state"] = observed_state
    body["reconcile_status"] = status
    body["reconcile_retry_count"] = int(retry_count)
    body["reconcile_last_attempt_at"] = _stamp()
    body["reconcile_next_retry_at"] = next_retry_at
    body["reconcile_last_error"] = error
    body["reconcile_drift"] = drift
    body["reconcile_last_action"] = recovery_action
    if status == "healthy":
        body["reconcile_last_success_at"] = _stamp()
    return instance_runtime.register_instance(body)


def _backoff(config: dict[str, Any], retry_count: int) -> int:
    _, base, maximum = _settings(config)
    return min(maximum, base * (2 ** max(0, retry_count - 1)))


def _failure(config: dict[str, Any], record: dict[str, Any], exc: Exception, *, drift: str | None = None) -> dict[str, Any]:
    previous = int(record.get("reconcile_retry_count") or 0)
    retries = previous + 1
    threshold, _, _ = _settings(config)
    delay = _backoff(config, retries)
    next_retry = _stamp(_now() + timedelta(seconds=delay))
    status = "degraded" if retries >= threshold else "retry_wait"
    error = str(exc)[:2000]
    updated = _save(record, status=status, drift=drift, retry_count=retries, next_retry_at=next_retry, error=error)
    _event(
        "INSTANCE_DEGRADED" if status == "degraded" else "INSTANCE_RECONCILE_FAILED",
        updated,
        {"retry_count": retries, "next_retry_at": next_retry, "error": error, "drift": drift},
    )
    return {
        "instance_id": record["instance_id"],
        "status": status,
        "retry_count": retries,
        "next_retry_at": next_retry,
        "error": error,
        "drift": drift,
    }


def reconcile_instance(config: dict[str, Any], instance_id: str, *, force: bool = False) -> dict[str, Any]:
    record = instance_runtime._owned(config, instance_id)
    normalized = validate_runtime_spec(record, expected_agent_id=str(config.get("agent_id") or ""))
    retry_at = _parse(record.get("reconcile_next_retry_at"))
    if not force and retry_at is not None and retry_at > _now():
        return {
            "instance_id": normalized["instance_id"],
            "status": str(record.get("reconcile_status") or "retry_wait"),
            "retry_count": int(record.get("reconcile_retry_count") or 0),
            "next_retry_at": _stamp(retry_at),
            "skipped": True,
        }

    _event("INSTANCE_RECONCILE_STARTED", normalized, {"desired_state": normalized["desired_state"]})
    drift: str | None = None
    recovered = False
    recovery_action: str | None = None
    try:
        materializer = resolve_materializer(normalized)
        materialized = materializer.inspect(normalized)
        if materialized.get("exists") and not materialized.get("owned"):
            drift = "ownership_violation"
            _event("INSTANCE_DRIFT_DETECTED", normalized, {"drift": drift})
            raise PermissionError("runtime ownership validation failed; automatic repair refused")
        if not materialized.get("exists"):
            drift = "runtime_missing"
        elif not materialized.get("matches"):
            drift = "runtime_modified"
        if drift:
            _event("INSTANCE_DRIFT_DETECTED", normalized, {"drift": drift})
            privileged_materialization.materialize(config, normalized)
            recovered = True
            recovery_action = "rematerialize"

        adapter = resolve_adapter(normalized)
        before = adapter.status(normalized)
        observed_before = instance_runtime._observed_state(before, record.get("observed_state"))
        desired = normalized["desired_state"]
        if desired == "running" and observed_before != "running":
            if drift is None:
                drift = "process_not_running"
                _event("INSTANCE_DRIFT_DETECTED", normalized, {"drift": drift, "observed_state": observed_before})
            recovery_action = "start"
            recovered = True
        elif desired == "stopped" and observed_before == "running":
            if drift is None:
                drift = "unexpected_running"
                _event("INSTANCE_DRIFT_DETECTED", normalized, {"drift": drift, "observed_state": observed_before})
            recovery_action = "stop"
            recovered = True

        result = runtime_materialization.reconcile(config, normalized["instance_id"])
        observed = str(result.get("observed_state") or "unknown")
        converged = (desired == "running" and observed == "running") or (desired == "stopped" and observed == "stopped")
        if not converged:
            raise RuntimeError(f"runtime did not converge: desired={desired} observed={observed}")
        latest = instance_runtime._owned(config, normalized["instance_id"])
        updated = _save(
            latest,
            status="healthy",
            observed_state=observed,
            drift=None,
            retry_count=0,
            next_retry_at=None,
            error=None,
            recovery_action=recovery_action,
        )
        event_type = "INSTANCE_RECOVERED" if recovered else "INSTANCE_RECONCILE_COMPLETED"
        _event(event_type, updated, {"desired_state": desired, "observed_state": observed, "action": recovery_action})
        return {
            "instance_id": normalized["instance_id"],
            "status": "healthy",
            "desired_state": desired,
            "observed_state": observed,
            "recovered": recovered,
            "action": recovery_action,
            "retry_count": 0,
        }
    except Exception as exc:
        latest = instance_runtime.get_instance(normalized["instance_id"]) or record
        return _failure(config, latest, exc, drift=drift)


def reconcile_all(config: dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in instance_runtime.list_instances(config):
        instance_id = str(item.get("instance_id") or "")
        if not instance_id:
            continue
        try:
            results.append(reconcile_instance(config, instance_id, force=force))
        except Exception as exc:
            results.append({"instance_id": instance_id, "status": "failed", "error": str(exc)[:2000]})
    return results


def reconciliation_inventory(config: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for item in instance_runtime.list_instances(config):
        instance_id = str(item.get("instance_id") or "")
        record = instance_runtime.get_instance(instance_id) if instance_id else None
        if not record:
            continue
        values.append({
            "instance_id": instance_id,
            "desired_state": record.get("desired_state"),
            "observed_state": record.get("observed_state", "unknown"),
            "reconcile_status": record.get("reconcile_status", "unknown"),
            "retry_count": int(record.get("reconcile_retry_count") or 0),
            "last_attempt_at": record.get("reconcile_last_attempt_at"),
            "last_success_at": record.get("reconcile_last_success_at"),
            "next_retry_at": record.get("reconcile_next_retry_at"),
            "last_error": record.get("reconcile_last_error"),
            "drift": record.get("reconcile_drift"),
        })
    return values


__all__ = ["reconcile_all", "reconcile_instance", "reconciliation_inventory"]
