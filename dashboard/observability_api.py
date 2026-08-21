#!/usr/bin/env python3
"""Administrative read API for Universal Observability."""

from __future__ import annotations

from typing import Any

from observability_repository import ObservabilityRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def query_observability(*, user, backend, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    _require_admin(user)
    values = filters if isinstance(filters, dict) else {}
    mode = str(values.get("mode") or "latest").strip().lower()
    repo = ObservabilityRepository(backend)
    repo.initialize()
    common = {
        "agent_id": values.get("agent_id"),
        "instance_id": values.get("instance_id"),
        "metric_name": values.get("metric_name"),
        "limit": int(values.get("limit") or 500),
    }
    if mode == "latest":
        rows = repo.latest(**common)
        kind = "CapivaraObservabilityLatest"
    elif mode == "history":
        rows = repo.history(**common, since=values.get("since"), until=values.get("until"))
        kind = "CapivaraObservabilityHistory"
    elif mode == "summary":
        rows = repo.summary(**common, since=values.get("since"), until=values.get("until"))
        kind = "CapivaraObservabilitySummary"
    else:
        raise ValueError("unsupported observability mode")
    return {"schema_version": 1, "kind": kind, "mode": mode, "metrics": rows, "count": len(rows)}


__all__ = ["query_observability"]
