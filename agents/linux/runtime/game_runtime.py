#!/usr/bin/env python3
"""Game profile orchestration at the boundary between provisioning and B8 runtime materialization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import instance_runtime
import provisioning_state
from catalog_runtime_policy import apply_policy
from profiles import resolve_profile
from runtime_events import emit_runtime_event
from runtime_materialization import materialize
from runtime_spec import validate_runtime_spec

_PROFILE_CONTEXT_KEYS = (
    "install_path", "content_root", "working_directory", "executable", "ports", "environment", "arguments", "user",
    "desired_state", "instance_state_root", "config_path", "mission", "dayz_mission", "catalog_runtime_policy",
    "variables", "runtime_variables", "resource_profile",
)


def _profile_context(context: dict[str, Any]) -> dict[str, Any]:
    """Persist only the structured inputs required to rebuild a RuntimeSpec later."""
    return {key: context[key] for key in _PROFILE_CONTEXT_KEYS if key in context}


def _historical_provisioning_context(instance_id: str) -> dict[str, Any]:
    """Recover structured inputs that pre-profile RuntimeSpecs may have discarded.

    The provisioning request is authoritative for reserved ports because those values
    were assigned before runtime materialization. Newest matching history wins and
    existing RuntimeSpec values are never overwritten by this fallback.
    """
    root = Path(provisioning_state.HISTORY_ROOT)
    try:
        candidates = sorted(
            root.glob("*.request.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return {}
    for path in candidates:
        payload = provisioning_state.read_json(path)
        if not isinstance(payload, dict):
            continue
        if str(payload.get("instance_id") or "").strip() != instance_id:
            continue
        recovered: dict[str, Any] = {}
        ports = payload.get("ports")
        if isinstance(ports, dict) and ports:
            recovered["ports"] = dict(ports)
        for key in (
            "environment_id", "runtime_id", "catalog_runtime_policy", "mission", "dayz_mission",
            "resource_profile", "resource_profile_id",
        ):
            if key in payload:
                recovered[key] = payload[key]
        return recovered
    return {}


def _hydrate_legacy_context(record: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Fill only missing migration context from the matching provisioning history."""
    instance_id = str(record.get("instance_id") or record.get("id") or "").strip()
    if not instance_id:
        return context
    historical = _historical_provisioning_context(instance_id)
    if not historical:
        return context

    hydrated = dict(context)
    current_ports = hydrated.get("ports")
    merged_ports = dict(current_ports) if isinstance(current_ports, dict) else {}
    historical_ports = historical.get("ports")
    if isinstance(historical_ports, dict):
        for role, binding in historical_ports.items():
            if role not in merged_ports and isinstance(binding, dict):
                merged_ports[role] = dict(binding)
    if merged_ports:
        hydrated["ports"] = merged_ports

    for key, value in historical.items():
        if key == "ports":
            continue
        if key not in hydrated or hydrated.get(key) in (None, "", [], {}):
            hydrated[key] = value
    return hydrated


def build_runtime_spec(config: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(instance, dict) or not isinstance(context, dict):
        raise ValueError("instance and runtime context must be objects")
    agent_id = str(config.get("agent_id") or "").strip()
    if not agent_id:
        raise ValueError("Agent identity is required")
    if str(instance.get("agent_id") or "").strip() != agent_id:
        raise PermissionError("instance belongs to another Agent")
    profile = resolve_profile(instance)
    raw = profile.build_runtime_spec(dict(instance), dict(context))
    raw = apply_policy(raw, instance, context)
    normalized = validate_runtime_spec(raw, expected_agent_id=agent_id)
    normalized["game_id"] = str(raw.get("game_id") or instance.get("game_id") or "").strip().lower()
    normalized["environment_id"] = str(raw.get("environment_id") or instance.get("environment_id") or "").strip()
    normalized["profile"] = str(raw.get("profile") or normalized["game_id"])
    normalized["profile_version"] = int(raw.get("profile_version") or getattr(profile, "profile_version", 1))
    normalized["profile_context"] = _profile_context(context)
    for key in ("ports", "catalog_runtime_policy", "catalog_templates", "catalog_network_properties", "catalog_variables"):
        if key in raw:
            normalized[key] = raw[key]
    emit_runtime_event(
        Path(instance_runtime.STATE_DIR),
        "INSTANCE_RUNTIME_PROFILE_RESOLVED",
        instance_id=normalized["instance_id"],
        agent_id=agent_id,
        data={
            "game_id": normalized["game_id"],
            "environment_id": normalized["environment_id"],
            "profile": normalized["profile"],
            "profile_version": normalized["profile_version"],
            "catalog_policy": bool(context.get("catalog_runtime_policy")),
        },
    )
    return normalized


def migrate_runtime_spec(config: dict[str, Any], record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Rebuild a persisted RuntimeSpec when its registered profile is older than the installed profile.

    Records created before game-profile orchestration may not carry any game/profile
    identity at all. Those generic B8/B11 records remain valid and are reconciled
    unchanged; migration only applies once an instance identifies a game profile.
    """
    if not isinstance(record, dict):
        raise ValueError("runtime record must be an object")
    if not any(str(record.get(key) or "").strip() for key in ("game_id", "environment_id", "profile")):
        return record, False

    profile = resolve_profile(record)
    current_version = int(getattr(profile, "profile_version", 1))
    stored_version = int(record.get("profile_version") or 1)
    if stored_version > current_version:
        raise RuntimeError(
            f"runtime profile downgrade refused: persisted={stored_version} installed={current_version}"
        )
    if stored_version == current_version:
        return record, False

    persisted_context = record.get("profile_context")
    if isinstance(persisted_context, dict) and persisted_context:
        context = dict(persisted_context)
    else:
        context = profile.migration_context(dict(record))
    if not isinstance(context, dict) or not context:
        raise RuntimeError(
            f"runtime profile migration unavailable: profile={record.get('profile') or record.get('game_id')} "
            f"persisted={stored_version} installed={current_version}"
        )
    context = _hydrate_legacy_context(record, context)

    instance = dict(record)
    instance["desired_state"] = str(record.get("desired_state") or "stopped")
    rebuilt = build_runtime_spec(config, instance, context)
    rebuilt_version = int(rebuilt.get("profile_version") or 1)
    if rebuilt_version <= stored_version:
        raise RuntimeError(
            f"runtime profile migration did not advance version: persisted={stored_version} rebuilt={rebuilt_version}"
        )
    if record.get("created_at"):
        rebuilt["created_at"] = record["created_at"]
    rebuilt["profile_migrated_from_version"] = stored_version
    return rebuilt, True


def materialize_profile(config: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    spec = build_runtime_spec(config, instance, context)
    result = materialize(config, spec)
    result["profile"] = {"name": spec["profile"], "version": spec["profile_version"]}
    return result


__all__ = ["build_runtime_spec", "materialize_profile", "migrate_runtime_spec"]
