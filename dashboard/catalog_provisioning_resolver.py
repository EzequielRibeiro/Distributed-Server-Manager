#!/usr/bin/env python3
"""Resolve Catalog artifacts that become part of an Agent provisioning request."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from catalog_controller_runtime_policy import load_policy
from agent_game_data_api import prepare_runtime_selection

ROOT = Path(__file__).resolve().parents[1]

def _runtime(runtime_id: str, root: Path = ROOT) -> dict[str, Any]:
    for path in (root / "catalog" / "v2" / "games").glob("*/runtimes/*.json"):
        try: payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if isinstance(payload, dict) and str(payload.get("id") or "") == str(runtime_id): return payload
    raise ValueError("runtime not found in Catalog")

def _profiles(game: str, root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / "catalog" / "v2" / "games" / str(game) / "resource-profiles.json"
    if not path.is_file(): return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item) for item in payload.get("profiles", []) if isinstance(item, dict)] if isinstance(payload, dict) else []

def resolve_catalog_provisioning(*, environment_id: str, selector: str, selection: dict[str, Any] | None, configuration: dict[str, Any] | None, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = _runtime(environment_id, root)
    resolved_selection = dict(selection or {})
    if not resolved_selection:
        resolved_selection = prepare_runtime_selection(root, environment_id, selector)
    if str(resolved_selection.get("environment_id") or environment_id) != environment_id:
        raise ValueError("runtime selection does not match environment_id")
    config = dict(configuration or {})
    policy = load_policy(root, runtime)
    config["catalog_runtime_policy"] = policy
    profiles = _profiles(str(runtime.get("game") or ""), root)
    requested = str(config.get("resource_profile_id") or "").strip()
    allowed = config.get("allowed_resource_profiles")
    if allowed is not None:
        if not isinstance(allowed, list): raise ValueError("allowed_resource_profiles must be a list")
        allowed_ids = {str(item) for item in allowed}
        if requested and requested not in allowed_ids: raise PermissionError("resource profile is not allowed by contract")
    if profiles:
        profile = next((item for item in profiles if str(item.get("id") or "") == requested), None) if requested else profiles[0]
        if profile is None: raise ValueError("resource profile not found in Catalog")
        if allowed is not None and str(profile.get("id") or "") not in {str(item) for item in allowed}: raise PermissionError("resource profile is not allowed by contract")
        config["resource_profile_id"] = str(profile.get("id") or "")
        config["resource_profile"] = profile
    config["catalog_runtime_id"] = str(runtime.get("id") or environment_id)
    config["catalog_game_id"] = str(runtime.get("game") or "")
    return resolved_selection, config

__all__ = ["resolve_catalog_provisioning"]
