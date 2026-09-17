#!/usr/bin/env python3
"""Read game/runtime capabilities for Customer Instance Workspace v2.

``workspace-policy.json`` carries customer UX/contract defaults while the
RuntimeDefinition owns executable managed-content capabilities. During migration,
legacy workspace booleans remain a fallback only when a RuntimeDefinition does not
yet declare ``content.managed``. Missing declarations fail closed.

M7 maintenance capabilities are different: they are security-sensitive execution
contracts and therefore come from the canonical 1:1 inventory at
``catalog/v2/maintenance-capabilities.json``. Runtime/workspace declarations may
remain during migration, but they must agree with that inventory exactly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/"core"
if str(CORE) not in sys.path:sys.path.insert(0,str(CORE))
from maintenance_platform import normalize_capabilities as normalize_maintenance_capabilities
from instance_workspace_policy import effective_content_policy


MAINTENANCE_CAPABILITIES = (
    "scheduled_restart",
    "broadcast",
    "save",
    "graceful_shutdown",
    "native_countdown",
)


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


def maintenance_capability_inventory(root: Path) -> dict[str, dict[str, bool]]:
    """Return the canonical M7 per-runtime maintenance capability inventory.

    A missing inventory is fail-closed at runtime so partial/test installations do
    not accidentally gain native capabilities. The M7 CI gate separately requires
    a complete 1:1 inventory for every RuntimeDefinition shipped by the catalog.
    """
    path = Path(root) / "catalog" / "v2" / "maintenance-capabilities.json"
    payload = _read_json(path)
    if not payload:
        return {}
    if payload.get("kind") != "MaintenanceCapabilityInventory":
        raise RuntimeError("invalid maintenance capability inventory")
    declared = payload.get("capabilities")
    if not isinstance(declared, list) or tuple(declared) != MAINTENANCE_CAPABILITIES:
        raise RuntimeError("invalid maintenance capability inventory schema")
    runtimes = payload.get("runtimes")
    if not isinstance(runtimes, dict):
        raise RuntimeError("invalid maintenance capability inventory runtimes")

    result: dict[str, dict[str, bool]] = {}
    for raw_key, raw_value in runtimes.items():
        key = str(raw_key or "").strip().lower()
        if not key or not isinstance(raw_value, dict):
            raise RuntimeError("invalid maintenance capability inventory entry")
        if set(raw_value) != set(MAINTENANCE_CAPABILITIES):
            raise RuntimeError(f"incomplete maintenance capability inventory entry: {key}")
        if not all(isinstance(raw_value[name], bool) for name in MAINTENANCE_CAPABILITIES):
            raise RuntimeError(f"invalid maintenance capability types: {key}")
        result[key] = {name: raw_value[name] for name in MAINTENANCE_CAPABILITIES}
    return result


def runtime_maintenance_capabilities(
    root: Path,
    game_id: str,
    runtime_id: str,
    *,
    definition: dict[str, Any] | None = None,
    workspace: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Resolve maintenance capabilities from the canonical M7 inventory.

    Legacy declarations are accepted only when they agree with the canonical
    inventory. Missing entries deliberately fall back to the generic safe contract
    (scheduled restart only, no game-native operation); CI prevents shipping such a
    gap in the repository catalog.
    """
    game = _safe_game(game_id)
    runtime = _safe_runtime(runtime_id)
    key = f"{game}/{runtime}"
    raw = maintenance_capability_inventory(root).get(key)
    canonical = normalize_maintenance_capabilities(raw or {})

    for source_name, source in (("runtime", definition), ("workspace", workspace)):
        if not isinstance(source, dict):
            continue
        legacy = source.get("maintenance")
        if not isinstance(legacy, dict):
            continue
        normalized = normalize_maintenance_capabilities(legacy)
        if normalized != canonical:
            raise RuntimeError(
                f"maintenance capability drift for {key}: {source_name} declaration disagrees with canonical inventory"
            )
    return canonical


def runtime_workspace_capabilities(root: Path, game_id: str, runtime_id: str) -> dict[str, Any]:
    policy = game_workspace_catalog(root, game_id)
    runtime = _safe_runtime(runtime_id)
    item = (policy.get("runtimes") or {}).get(runtime)
    if not isinstance(item, dict):
        item = {}
    definition = runtime_definition(root, game_id, runtime)
    content = definition.get("content") if isinstance(definition, dict) else {}
    managed = content.get("managed") if isinstance(content, dict) else None
    managed_types = managed.get("types") if isinstance(managed, dict) else None
    authoritative = isinstance(managed_types, dict)
    mods = "mod" in managed_types if authoritative else bool(item.get("mods"))
    plugins = "plugin" in managed_types if authoritative else bool(item.get("plugins"))
    datapacks = "datapack" in managed_types if authoritative else False
    bundles = content.get("bundles") if isinstance(content, dict) else {}
    modpack = bundles.get("modpack") if isinstance(bundles, dict) else None
    modpacks = isinstance(modpack, dict) and bool(modpack.get("providers"))
    providers: dict[str, list[str]] = {}
    if authoritative:
        for content_type, declaration in managed_types.items():
            if not isinstance(declaration, dict):
                continue
            declared = declaration.get("providers")
            if isinstance(declared, list):
                providers[str(content_type)] = sorted({str(value).strip().lower() for value in declared if str(value).strip()})
    if modpacks:
        providers["modpack"] = sorted({str(value).strip().lower() for value in modpack.get("providers") or [] if str(value).strip()})
    if bool(item.get("workshop")):
        providers["workshop"] = ["steam-workshop"]
    maintenance = runtime_maintenance_capabilities(
        root,
        game_id,
        runtime,
        definition=definition,
        workspace=item,
    )
    return {
        "mods": mods,
        "plugins": plugins,
        "datapacks": datapacks,
        "modpacks": modpacks,
        "providers": providers,
        "workshop": bool(item.get("workshop")),
        "external_upload": bool(item.get("external_upload", True)),
        "custom_runtime": bool(item.get("custom_runtime", False)),
        "console": dict(item.get("console") or {}),
        "startup_parameters": dict(item.get("startup_parameters") or {}),
        "server_settings": dict(definition.get("server_settings") or item.get("server_settings") or {}),
        "maintenance": maintenance,
        "file_policy": dict(item.get("file_policy") or {}),
        "label": str(item.get("label") or definition.get("name") or runtime),
        "family": str(item.get("family") or definition.get("edition") or ""),
    }


def contract_entitlements(contract_metadata: dict[str, Any] | None) -> dict[str, bool]:
    metadata = contract_metadata if isinstance(contract_metadata, dict) else {}
    raw = metadata.get("entitlements") if isinstance(metadata.get("entitlements"), dict) else {}
    mode = str(metadata.get("content_mode") or metadata.get("product_variant") or "standard").lower()
    modified = mode in {"modified", "modded", "community", "workshop"}
    mods = bool(raw.get("mods", modified))
    return {
        "mods": mods,
        "plugins": bool(raw.get("plugins", modified)),
        "modpacks": bool(raw.get("modpacks", mods)),
        "datapacks": bool(raw.get("datapacks", mods)),
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
    if any((capabilities["mods"], capabilities["plugins"], capabilities["modpacks"], capabilities["datapacks"], capabilities["workshop"])) and not effective.modifications_allowed:
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
    "maintenance_capability_inventory", "runtime_allowed_by_contract",
    "runtime_definition", "runtime_maintenance_capabilities",
    "runtime_workspace_capabilities",
]
