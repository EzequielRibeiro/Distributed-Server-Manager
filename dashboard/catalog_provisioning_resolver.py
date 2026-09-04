#!/usr/bin/env python3
"""Resolve Catalog artifacts that become part of an Agent provisioning request."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from catalog_controller_runtime_policy import load_policy
from agent_game_data_api import prepare_runtime_selection
from core.catalog_resource_profile_policy import load_game_resource_profiles, resolve_catalog_resource_profile
from core.effective_resource_policy import normalize_resource_policy
from core.canonical_parameter_policy import canonicalize_parameter_payload

ROOT = Path(__file__).resolve().parents[1]

def _runtime(runtime_id: str, root: Path = ROOT) -> dict[str, Any]:
    for path in (root / "catalog" / "v2" / "games").glob("*/runtimes/*.json"):
        try: payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if isinstance(payload, dict) and str(payload.get("id") or "") == str(runtime_id): return payload
    raise ValueError("runtime not found in Catalog")

def resolve_catalog_resource_policy(*, root: Path, game_id: str, resource_profile_id: str | None = None) -> tuple[str | None, dict[str, Any], dict[str, int | float]]:
    profile_id, profile, _catalog = resolve_catalog_resource_profile(
        root=root,
        game_id=game_id,
        requested_profile_id=resource_profile_id,
        require_catalog=False,
    )
    if profile_id is None:
        return None, {}, {}
    effective = normalize_resource_policy(profile)
    return profile_id, profile, effective.as_dict()

def resolve_catalog_provisioning(*, environment_id: str, selector: str, selection: dict[str, Any] | None, configuration: dict[str, Any] | None, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = _runtime(environment_id, root)
    resolved_selection = dict(selection or {})
    if not resolved_selection:
        resolved_selection = prepare_runtime_selection(root, environment_id, selector)
    if str(resolved_selection.get("environment_id") or environment_id) != environment_id:
        raise ValueError("runtime selection does not match environment_id")
    config = dict(configuration or {})
    policy = canonicalize_parameter_payload(load_policy(root, runtime))
    config["catalog_runtime_policy"] = policy
    config["canonical_parameter_policy"] = {
        "arguments": list(policy.get("arguments") or []),
        "environment": dict(policy.get("environment") or {}),
    }
    game_id = str(runtime.get("game") or "")
    profile_catalog = load_game_resource_profiles(root, game_id)
    profiles = [dict(item) for item in profile_catalog.get("profiles", []) if isinstance(item, dict)]
    requested = str(config.get("resource_profile_id") or "").strip()
    allowed = config.get("allowed_resource_profiles")
    if allowed is not None:
        if not isinstance(allowed, list): raise ValueError("allowed_resource_profiles must be a list")
        allowed_ids = {str(item) for item in allowed}
        if requested and requested not in allowed_ids: raise PermissionError("resource profile is not allowed by contract")
    resolved_profile_id, profile, _profile_catalog = resolve_catalog_resource_profile(
        root=root,
        game_id=game_id,
        requested_profile_id=requested or None,
        require_catalog=False,
    )
    if resolved_profile_id is not None:
        if allowed is not None and resolved_profile_id not in {str(item) for item in allowed}: raise PermissionError("resource profile is not allowed by contract")
        effective = normalize_resource_policy(profile)
        config["resource_profile_id"] = resolved_profile_id
        config["resource_profile"] = profile
        config["effective_resource_policy"] = effective.as_dict()
        config["agent_resource_limits"] = effective.agent_resources()
    config["catalog_runtime_id"] = str(runtime.get("id") or environment_id)
    config["catalog_game_id"] = str(runtime.get("game") or "")
    return resolved_selection, config

__all__ = ["resolve_catalog_provisioning", "resolve_catalog_resource_policy"]
