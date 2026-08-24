#!/usr/bin/env python3
"""Persistent HTTP contract for game resource profiles stored in Catalog v2."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

RESOURCE_PROFILES_PATH = "/api/catalog/resource-profiles"
_GAME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def catalog_resource_profiles(root: Path, game: str) -> dict[str, Any]:
    game = str(game or "").strip().lower()
    if not _GAME_ID.fullmatch(game):
        raise ValueError("valid game is required")
    overrides_root = (root / "config" / "catalog-resource-profiles").resolve()
    override = (overrides_root / f"{game}.json").resolve()
    games_root = (root / "catalog" / "v2" / "games").resolve()
    catalog_path = (games_root / game / "resource-profiles.json").resolve()
    path = override if override.is_file() else catalog_path
    allowed_root = overrides_root if path == override else games_root
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("invalid catalog path") from exc
    if not path.is_file():
        return {"schema_version": 2, "kind": "GameResourceProfiles", "game": game, "profiles": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "GameResourceProfiles" or payload.get("game") != game:
        raise RuntimeError("invalid resource profile catalog")
    return payload


def save_catalog_resource_profiles(root: Path, game: str, profiles: Any) -> dict[str, Any]:
    game = str(game or "").strip().lower()
    if not _GAME_ID.fullmatch(game):
        raise ValueError("valid game is required")
    game_dir = root / "catalog" / "v2" / "games" / game
    if not game_dir.is_dir():
        raise ValueError("game is not registered in Catalog")
    if not isinstance(profiles, list):
        raise ValueError("profiles must be a list")
    if not profiles:
        raise ValueError("at least one resource profile is required")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            raise ValueError("invalid resource profile")
        identifier = str(item.get("id") or "").strip().lower()
        name = str(item.get("name") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", identifier) or identifier in identifiers:
            raise ValueError("resource profile IDs must be unique and valid")
        if not name:
            raise ValueError("resource profile name is required")
        try:
            memory_mb = int(item.get("memory_mb")); storage_mb = int(item.get("storage_mb"))
            cpu_cores = float(item.get("cpu_cores")); swap_mb = int(item.get("swap_mb") or 0)
            pids_limit = int(item.get("pids_limit") or 512)
        except (TypeError, ValueError) as exc:
            raise ValueError("resource profile values must be numeric") from exc
        if memory_mb < 256 or storage_mb < 1024 or cpu_cores <= 0 or swap_mb < 0 or pids_limit < 1:
            raise ValueError("resource profile values are outside the allowed range")
        identifiers.add(identifier)
        normalized.append({"id": identifier, "name": name, "description": str(item.get("description") or "").strip(),
                           "memory_mb": memory_mb, "storage_mb": storage_mb, "cpu_cores": cpu_cores,
                           "swap_mb": swap_mb, "pids_limit": pids_limit})
    payload = {"schema_version": 2, "kind": "GameResourceProfiles", "game": game, "profiles": normalized}
    target = root / "config" / "catalog-resource-profiles" / f"{game}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return payload


def dispatch_catalog_resource_profiles_get(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if not user or str(user.get("role") or "").lower() not in {"admin", "controller", "operator", "customer"}:
        return 403, {"error": "forbidden", "message": "catalog administration access required"}
    query = parse_qs(query_string, keep_blank_values=True)
    try:
        return 200, catalog_resource_profiles(root, (query.get("game") or [""])[0])
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except json.JSONDecodeError:
        return 500, {"error": "invalid_catalog", "message": "Resource profile catalog contains invalid JSON."}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível carregar os perfis de recursos."}


def dispatch_catalog_resource_profiles_put(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if not user or str(user.get("role") or "").lower() not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "catalog write access required"}
    body = payload if isinstance(payload, dict) else {}
    try:
        return 200, save_catalog_resource_profiles(root, body.get("game"), body.get("profiles"))
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível salvar os perfis de recursos."}


__all__ = ["RESOURCE_PROFILES_PATH", "catalog_resource_profiles", "dispatch_catalog_resource_profiles_get", "dispatch_catalog_resource_profiles_put", "save_catalog_resource_profiles"]
