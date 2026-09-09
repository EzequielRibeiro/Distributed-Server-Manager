#!/usr/bin/env python3
"""Canonical Controller projection for Agent-owned instance runtime state.

The legacy Dashboard runtime contract was created around
``runtime/resources/<node>/<game>/<instance>``. Distributed and Hybrid Agents
can own perfectly valid instances without that filesystem projection, so the
Controller must use the database-backed Agent runtime-health inventory as the
runtime authority.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from agent_runtime_repository import AgentRuntimeRepository

_LIVE_AGENT_HEALTH = {"online", "degraded"}
_ONLINE_STATES = {"online", "running", "started", "active"}
_OFFLINE_STATES = {"offline", "stopped", "inactive"}
_FAILED_STATES = {"failed", "error"}
_TRANSIENT_STATES = {
    "attention",
    "creating",
    "installing",
    "pending_steam_auth",
    "provisioning",
    "queued",
    "restarting",
    "starting",
    "stopping",
    "updating",
    "warning",
}


def canonical_runtime_state(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in _ONLINE_STATES:
        return "online"
    if raw in _OFFLINE_STATES:
        return "offline"
    if raw in _FAILED_STATES:
        return "failed"
    if raw in _TRANSIENT_STATES:
        return raw
    return "unknown"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _safe_text(row.get("node_id") or row.get("server")),
        _safe_text(row.get("game_id") or row.get("game")),
        _safe_text(row.get("id") or row.get("instance") or row.get("instance_id")),
    )


def _metadata_from_record(row: dict[str, Any]) -> dict[str, Any]:
    server, game, instance = _identity(row)
    metadata = {
        "id": instance,
        "instance_id": instance,
        "node_id": server,
        "server": server,
        "game_id": game,
        "game": game,
        "agent_id": _safe_text(row.get("agent_id")),
        "customer_id": _safe_text(row.get("customer_id")),
        "name": row.get("name") or row.get("display_name") or instance,
        "display_name": row.get("display_name") or row.get("name") or instance,
        "status": row.get("status") or "unknown",
    }
    for field in ("installation_id", "region_id", "datacenter_id", "created_at"):
        if row.get(field) is not None:
            metadata[field] = row.get(field)
    return metadata


def _projected_state(
    *,
    record: dict[str, Any],
    runtime_health: dict[str, Any] | None,
    agent_health: str,
    fallback_state: Any,
    fallback_health: Any,
) -> dict[str, Any]:
    """Resolve one state without presenting stale Controller facts as live truth."""
    agent_id = _safe_text(record.get("agent_id"))
    fallback = canonical_runtime_state(fallback_state)
    health = _safe_text(fallback_health).lower() or "unknown"

    if not agent_id:
        return {
            "state": fallback,
            "health": health,
            "source": "persisted",
            "agent_health": "unknown",
        }

    agent_health = _safe_text(agent_health).lower() or "unknown"
    observation = runtime_health if isinstance(runtime_health, dict) else {}
    observed_state = canonical_runtime_state(observation.get("observed_state"))

    if agent_health in _LIVE_AGENT_HEALTH and observation:
        projected_health = _safe_text(observation.get("health")).lower() or "unknown"
        result = {
            "state": observed_state,
            "health": projected_health,
            "source": "agent",
            "agent_health": agent_health,
            "observed_state": _safe_text(observation.get("observed_state")).lower() or None,
            "desired_state": _safe_text(observation.get("desired_state")).lower() or None,
            "reconcile_status": _safe_text(observation.get("reconcile_status")).lower() or None,
            "operation_status": _safe_text(observation.get("operation_status")).lower() or None,
            "reported_at": observation.get("reported_at") or observation.get("updated_at"),
        }
        return result

    # Provisioning/failure is Controller workflow state, not an assertion that a
    # game process is currently online/offline, so it remains useful when Agent
    # runtime telemetry is temporarily unavailable.
    if fallback in _TRANSIENT_STATES or fallback == "failed":
        return {
            "state": fallback,
            "health": health,
            "source": "controller",
            "agent_health": agent_health,
        }

    # An Agent-owned instance with unavailable/stale telemetry must not inherit
    # a historic online/offline value from instances.status or server.json.
    return {
        "state": "unknown",
        "health": "stale" if agent_health == "offline" else "unknown",
        "source": "agent-stale" if agent_health == "offline" else "agent-unavailable",
        "agent_health": agent_health,
        "observed_state": _safe_text(observation.get("observed_state")).lower() or None,
        "desired_state": _safe_text(observation.get("desired_state")).lower() or None,
        "reported_at": observation.get("reported_at") or observation.get("updated_at"),
    }


def install_runtime_instance_projection(
    legacy,
    *,
    health_repository_factory: Callable[[Any], Any] | None = None,
    agent_repository_factory: Callable[[Any], Any] | None = None,
    cache_seconds: float = 2.0,
):
    """Install Agent-authoritative wrappers over legacy runtime list/detail APIs."""
    original_list = legacy.api_runtime_list
    original_summary = legacy.api_runtime_summary
    health_factory = health_repository_factory or AgentInstanceRuntimeHealthRepository
    agent_factory = agent_repository_factory or AgentRuntimeRepository
    cache_lock = threading.Lock()
    cache: dict[str, Any] = {"key": None, "expires": 0.0, "value": None}

    def build_snapshot(database_path):
        try:
            records = list(legacy.dashboard_repository(database_path).registered_instance_records())
        except Exception:
            records = []

        by_identity = {_identity(row): row for row in records if all(_identity(row))}
        runtime_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        agent_health: dict[str, str] = {}
        agent_ids = sorted({_safe_text(row.get("agent_id")) for row in records if _safe_text(row.get("agent_id"))})

        if agent_ids:
            try:
                backend = legacy.backend_from_environment()
                health_repository = health_factory(backend)
                agent_repository = agent_factory(backend)
                health_repository.initialize()
                agent_repository.initialize()

                for agent_id in agent_ids:
                    try:
                        snapshot = agent_repository.snapshot(agent_id)
                        agent_health[agent_id] = _safe_text(snapshot.get("health_status")).lower() or "unknown"
                    except Exception:
                        agent_health[agent_id] = "unknown"
                    try:
                        for item in health_repository.list_for_agent(agent_id):
                            instance_id = _safe_text(item.get("instance_id"))
                            if instance_id:
                                runtime_by_key[(agent_id, instance_id)] = dict(item)
                    except Exception:
                        continue
            except Exception:
                pass

        return {
            "records": records,
            "by_identity": by_identity,
            "runtime_by_key": runtime_by_key,
            "agent_health": agent_health,
        }

    def projection_snapshot(database_path):
        key = str(database_path)
        now = time.monotonic()
        with cache_lock:
            if cache["key"] == key and cache["value"] is not None and now < cache["expires"]:
                return cache["value"]
            value = build_snapshot(database_path)
            cache.update({"key": key, "expires": now + max(0.0, float(cache_seconds)), "value": value})
            return value

    def resource_exists(server: str, game: str, instance: str) -> bool:
        return (Path(legacy.DSM_ROOT) / "runtime" / "resources" / server / game / instance).is_dir()

    def project_resource(resource: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        result = dict(resource)
        identity = (
            _safe_text(result.get("server")),
            _safe_text(result.get("game")),
            _safe_text(result.get("instance")),
        )
        record = snapshot["by_identity"].get(identity)
        if record is None:
            return result

        agent_id = _safe_text(record.get("agent_id"))
        runtime_health = snapshot["runtime_by_key"].get((agent_id, identity[2])) if agent_id else None
        projection = _projected_state(
            record=record,
            runtime_health=runtime_health,
            agent_health=snapshot["agent_health"].get(agent_id, "unknown"),
            fallback_state=result.get("status"),
            fallback_health=result.get("health"),
        )
        result.update(
            {
                "status": projection["state"],
                "health": projection["health"],
                "status_source": projection["source"],
                "agent_id": agent_id,
                "agent_health": projection.get("agent_health", "unknown"),
            }
        )
        for field in ("observed_state", "desired_state", "reported_at", "reconcile_status", "operation_status"):
            if projection.get(field) is not None:
                result[field] = projection[field]
        return result

    def api_runtime_list(database_path=None):
        database_path = database_path or legacy.DATABASE_FILE
        resources = original_list(database_path)
        if not isinstance(resources, list):
            return resources
        snapshot = projection_snapshot(database_path)
        return [project_resource(item, snapshot) if isinstance(item, dict) else item for item in resources]

    def api_runtime_summary(server, game, instance):
        server = _safe_text(server)
        game = _safe_text(game)
        instance = _safe_text(instance)
        database_path = legacy.DATABASE_FILE
        snapshot = projection_snapshot(database_path)
        record = snapshot["by_identity"].get((server, game, instance))

        base_exists = resource_exists(server, game, instance)
        summary = original_summary(server, game, instance) if base_exists else None

        if record is None:
            if summary is not None:
                return summary
            return original_summary(server, game, instance)

        agent_id = _safe_text(record.get("agent_id"))
        runtime_health = snapshot["runtime_by_key"].get((agent_id, instance)) if agent_id else None

        fallback_state = record.get("status") or "unknown"
        fallback_health = "unknown"
        if isinstance(summary, dict):
            raw_server_state = summary.get("server_state") if isinstance(summary.get("server_state"), dict) else {}
            raw_status = raw_server_state.get("status", {})
            if isinstance(raw_status, dict):
                fallback_state = raw_status.get("state") or fallback_state
                fallback_health = raw_status.get("health") or raw_server_state.get("health") or fallback_health
            else:
                fallback_state = raw_status or fallback_state
                fallback_health = raw_server_state.get("health") or fallback_health

        projection = _projected_state(
            record=record,
            runtime_health=runtime_health,
            agent_health=snapshot["agent_health"].get(agent_id, "unknown"),
            fallback_state=fallback_state,
            fallback_health=fallback_health,
        )

        if not isinstance(summary, dict) or summary.get("error"):
            summary = {
                "server": server,
                "game": game,
                "instance": instance,
                "server_state": {},
                "mods": {},
                "metrics": {},
                "events": [],
                "backup": {},
                "instance_metadata": _metadata_from_record(record),
                "provision": {},
                "runtime_definition": {},
            }

        server_state = summary.get("server_state") if isinstance(summary.get("server_state"), dict) else {}
        server_state["status"] = {
            "state": projection["state"],
            "health": projection["health"],
        }
        server_state["source"] = projection["source"]
        server_state["agent_health"] = projection.get("agent_health", "unknown")
        server_state["identity"] = {"server": server, "game": game, "instance": instance}
        for field in ("observed_state", "desired_state", "reported_at", "reconcile_status", "operation_status"):
            if projection.get(field) is not None:
                server_state[field] = projection[field]
        summary["server_state"] = server_state

        metadata = summary.get("instance_metadata")
        if not isinstance(metadata, dict) or not metadata:
            summary["instance_metadata"] = _metadata_from_record(record)
        else:
            metadata.setdefault("agent_id", agent_id)
            metadata.setdefault("customer_id", _safe_text(record.get("customer_id")))
            metadata.setdefault("display_name", record.get("display_name") or record.get("name") or instance)

        return summary

    legacy.api_runtime_list = api_runtime_list
    legacy.api_runtime_summary = api_runtime_summary
    return {
        "api_runtime_list": api_runtime_list,
        "api_runtime_summary": api_runtime_summary,
    }


__all__ = ["canonical_runtime_state", "install_runtime_instance_projection"]
