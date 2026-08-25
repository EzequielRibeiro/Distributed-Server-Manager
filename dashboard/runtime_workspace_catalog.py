#!/usr/bin/env python3
"""Read game/runtime capabilities for Customer Instance Workspace v2.

The optional ``workspace-policy.json`` inside each game catalog is the single
place where customer-facing runtime capabilities are declared. Runtime files
remain responsible for installation/materialization. Missing declarations fail
closed for content and console capabilities.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from instance_workspace_policy import effective_content_policy


def _safe_game(game_id: str) -> str:
    value = str(game_id or "").strip().lower()
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
        raise ValueError("invalid game_id")
    return value


def _safe_runtime(runtime_id: str) -> str:
    value = str(runtime_id or "").strip().lower()
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):
        raise ValueError("invalid runtime_id")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid workspace catalog: {path}")
    return value


def game_workspace_catalog(root: Path, game_id: str) -> dict[str, Any]:
    game = _safe_game(game_id)
    game_dir = (Path(root) / "catalog" / "v2" / "games" / game).resolve()
    catalog_root = (Path(root) / "catalog" / "v2" / "games").resolve()
    game_dir.relative_to(catalog_root)
    payload = _read_json(game_dir / "workspace-policy.json")
    if not payload:
        return {"schema_version": 1, "kind": "GameWorkspacePolicy", "game": game, "products": {}, "runtimes": {}}
    if payload.get("kind") != "GameWorkspacePolicy" or str(payload.get("game") or "") != game:
        raise RuntimeError("invalid game workspace policy")
    return payload


def runtime_definition(root: Path, game_id: str, runtime_id: str) -> dict[str, Any]:
    game = _safe_game(game_id); runtime = _safe_runtime(runtime_id)
    runtime_dir = (Path(root) / "catalog" / "v2" / "games" / game / "runtimes").resolve()
    if not runtime_dir.is_dir(): return {}
    for path in sorted(runtime_dir.glob("*.json")):
        value = _read_json(path)
        if str(value.get("id") or "").strip().lower() == runtime:
            return value
    return {}


def runtime_workspace_capabilities(root: Path, game_id: str, runtime_id: str) -> dict[str, Any]:
    policy = game_workspace_catalog(root, game_id)
    runtime = _safe_runtime(runtime_id)
    item = (policy.get("runtimes") or {}).get(runtime)
    if not isinstance(item, dict):
        item = {}
    return {
        "mods": bool(item.get("mods")),
        "plugins": bool(item.get("plugins")),
        "workshop": bool(item.get("workshop")),
        "external_upload": bool(item.get("external_upload", True)),
        "custom_runtime": bool(item.get("custom_runtime", False)),
        "console": dict(item.get("console") or {}),
        "startup_parameters": dict(item.get("startup_parameters") or {}),
        "file_policy": dict(item.get("file_policy") or {}),
        "label": str(item.get("label") or runtime),
        "family": str(item.get("family") or ""),
    }


def contract_entitlements(contract_metadata: dict[str, Any] | None) -> dict[str, bool]:
    metadata = contract_metadata if isinstance(contract_metadata, dict) else {}
    raw = metadata.get("entitlements") if isinstance(metadata.get("entitlements"), dict) else {}
    mode = str(metadata.get("content_mode") or metadata.get("product_variant") or "standard").lower()
    modified = mode in {"modified", "modded", "community", "workshop"}
    return {
        "mods": bool(raw.get("mods", modified)),
        "plugins": bool(raw.get("plugins", modified)),
        "workshop": bool(raw.get("workshop", modified)),
        "external_upload": bool(raw.get("external_upload", True)),
        "custom_runtime": bool(raw.get("custom_runtime", False)),
    }


def runtime_allowed_by_contract(root: Path, game_id: str, runtime_id: str, contract_metadata: dict[str, Any] | None) -> bool:
    policy = game_workspace_catalog(root, game_id); runtime = _safe_runtime(runtime_id)
    item = (policy.get("runtimes") or {}).get(runtime)
    if not isinstance(item, dict): return False
    metadata = contract_metadata if isinstance(contract_metadata, dict) else {}
    product_id = str(metadata.get("product_variant") or metadata.get("content_mode") or "standard").lower()
    product = (policy.get("products") or {}).get(product_id)
    if isinstance(product, dict):
        allowed = product.get("allowed_runtimes")
        if isinstance(allowed, list) and allowed:
            return runtime in {str(value).lower() for value in allowed}
    capabilities = runtime_workspace_capabilities(root, game_id, runtime)
    effective = effective_content_policy(contract_entitlements(metadata), capabilities)
    if any((capabilities["mods"], capabilities["plugins"], capabilities["workshop"])) and not effective.modifications_allowed:
        return False
    return True


def allowed_runtimes(root: Path, game_id: str, contract_metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    policy = game_workspace_catalog(root, game_id); result = []
    for runtime_id, raw in sorted((policy.get("runtimes") or {}).items()):
        if not isinstance(raw, dict) or not runtime_allowed_by_contract(root, game_id, runtime_id, contract_metadata): continue
        definition = runtime_definition(root, game_id, runtime_id)
        result.append({
            "runtime_id": runtime_id,
            "label": raw.get("label") or definition.get("name") or runtime_id,
            "family": raw.get("family") or definition.get("edition"),
            "variant": definition.get("variant"),
            "capabilities": runtime_workspace_capabilities(root, game_id, runtime_id),
        })
    return result


__all__ = [
    "allowed_runtimes", "contract_entitlements", "game_workspace_catalog",
    "runtime_allowed_by_contract", "runtime_definition", "runtime_workspace_capabilities",
]
