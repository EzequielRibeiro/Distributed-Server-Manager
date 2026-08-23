#!/usr/bin/env python3
"""Game profile orchestration at the boundary between provisioning and B8 runtime materialization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import instance_runtime
from catalog_runtime_policy import apply_policy
from profiles import resolve_profile
from runtime_events import emit_runtime_event
from runtime_materialization import materialize
from runtime_spec import validate_runtime_spec


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
    normalized["profile_version"] = int(raw.get("profile_version") or 1)
    for key in ("ports", "config_path", "catalog_runtime_policy", "catalog_templates", "catalog_variables"):
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


def materialize_profile(config: dict[str, Any], instance: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    spec = build_runtime_spec(config, instance, context)
    result = materialize(config, spec)
    result["profile"] = {"name": spec["profile"], "version": spec["profile_version"]}
    return result


__all__ = ["build_runtime_spec", "materialize_profile"]
