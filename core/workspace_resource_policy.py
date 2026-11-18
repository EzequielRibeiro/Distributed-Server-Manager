"""Resolve instance workspace limits from stored policy, contracts and catalog."""

from pathlib import Path
from typing import Any

from core.catalog_resource_profile_policy import load_game_resource_profiles


def _number(source, key, kind=int):
    value = source.get(key)
    if value is None:
        return None
    try:
        return kind(value)
    except (TypeError, ValueError):
        return None


def resolve_workspace_resource_policy(
    root: Path, context: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    result = dict(policy or {})
    metadata = context.get("contract_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    instance_metadata = context.get("instance_metadata")
    if not isinstance(instance_metadata, dict):
        instance_metadata = {}
    resources = metadata.get("resources")
    if not isinstance(resources, dict):
        resources = {}
    effective = metadata.get("effective_resource_policy")
    if not isinstance(effective, dict):
        effective = {}

    profile_id = str(
        result.get("resource_profile_id")
        or metadata.get("resource_profile_id")
        or metadata.get("profile_id")
        or instance_metadata.get("resource_profile_id")
        or ""
    ).strip().lower()
    if profile_id and not result.get("resource_profile_id"):
        result["resource_profile_id"] = profile_id

    if result.get("cpu_limit_cores") is None:
        cpu = _number(effective, "cpu_cores", float)
        result["cpu_limit_cores"] = cpu if cpu is not None else _number(resources, "cpu_cores", float)
    byte_limits = (
        ("memory_limit_bytes", "memory_bytes", "memory_mb"),
        ("storage_limit_bytes", "storage_bytes", "storage_mb"),
    )
    for target, byte_key, mb_key in byte_limits:
        if result.get(target) is not None:
            continue
        value = _number(effective, byte_key)
        if value is None:
            value = _number(resources, byte_key)
        if value is None:
            mb = _number(resources, mb_key)
            value = mb * 1024 * 1024 if mb is not None else None
        result[target] = value
    if result.get("player_limit") is None:
        players = _number(effective, "player_limit")
        if players is None:
            key = "player_limit" if resources.get("player_limit") is not None else "slots"
            players = _number(resources, key)
        result["player_limit"] = players

    numeric_limits = ("cpu_limit_cores", "memory_limit_bytes", "storage_limit_bytes", "player_limit")
    if not profile_id or all(result.get(key) is not None for key in numeric_limits):
        return result
    try:
        catalog = load_game_resource_profiles(root, str(context.get("game_id") or ""))
    except (OSError, ValueError):
        return result
    profile = next(
        (item for item in catalog.get("profiles") or []
         if isinstance(item, dict) and str(item.get("id") or "").strip().lower() == profile_id),
        None,
    )
    if profile is None:
        return result

    if result.get("cpu_limit_cores") is None:
        result["cpu_limit_cores"] = _number(profile, "cpu_cores", float)
    for target, _, mb_key in byte_limits:
        if result.get(target) is None:
            mb = _number(profile, mb_key)
            result[target] = mb * 1024 * 1024 if mb is not None else None
    if result.get("player_limit") is None:
        result["player_limit"] = _number(profile, "player_limit")
    return result
