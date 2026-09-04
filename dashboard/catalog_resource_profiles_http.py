#!/usr/bin/env python3
"""Persistent HTTP contract for game resource profiles stored in Catalog v2."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from core.catalog_resource_profile_policy import (
    load_game_resource_profiles,
    normalize_game_id,
    normalize_resource_profile,
)

RESOURCE_PROFILES_PATH = "/api/catalog/resource-profiles"
_GAME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _normalize_profile(item: Any) -> dict[str, Any]:
    return normalize_resource_profile(item)


def _comparable_profiles(profiles: Any) -> list[dict[str, Any]] | None:
    if not isinstance(profiles, list):
        return None
    try:
        return [_normalize_profile(item) for item in profiles if isinstance(item, dict)]
    except ValueError:
        return None


def catalog_resource_profiles(root: Path, game: str) -> dict[str, Any]:
    game = normalize_game_id(game)
    return load_game_resource_profiles(root, game)


def save_catalog_resource_profiles(root: Path, game: str, profiles: Any, default_profile_id: Any = None) -> dict[str, Any]:
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
        profile = _normalize_profile(item)
        if profile["id"] in identifiers:
            raise ValueError("resource profile IDs must be unique and valid")
        identifiers.add(profile["id"])
        normalized.append(profile)
    default_profile_id = str(default_profile_id or "").strip().lower() or normalized[0]["id"]
    if default_profile_id not in identifiers:
        raise ValueError("default resource profile must reference an existing profile")
    payload = {"schema_version": 2, "kind": "GameResourceProfiles", "game": game,
               "default_profile_id": default_profile_id, "profiles": normalized}
    target = root / "config" / "catalog-resource-profiles" / f"{game}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return payload


def create_catalog_resource_profile(root: Path, game: str, profile: Any) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    item = _normalize_profile(profile)
    profiles = list(current.get("profiles") or [])
    if any(str(existing.get("id") or "").lower() == item["id"] for existing in profiles):
        raise ValueError("resource profile ID already exists")
    profiles.append(item)
    default_id = current.get("default_profile_id") or item["id"]
    return save_catalog_resource_profiles(root, game, profiles, default_id)


def update_catalog_resource_profile(root: Path, game: str, profile_id: str, profile: Any) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    original = str(profile_id or "").strip().lower()
    item = _normalize_profile(profile)
    profiles = list(current.get("profiles") or [])
    index = next((i for i, existing in enumerate(profiles) if str(existing.get("id") or "").lower() == original), None)
    if index is None:
        raise LookupError("resource profile not found")
    if item["id"] != original and any(str(existing.get("id") or "").lower() == item["id"] for i, existing in enumerate(profiles) if i != index):
        raise ValueError("resource profile ID already exists")
    profiles[index] = item
    default_id = current.get("default_profile_id")
    if default_id == original:
        default_id = item["id"]
    return save_catalog_resource_profiles(root, game, profiles, default_id)


def delete_catalog_resource_profile(root: Path, game: str, profile_id: str) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    identifier = str(profile_id or "").strip().lower()
    profiles = list(current.get("profiles") or [])
    if not any(str(item.get("id") or "").lower() == identifier for item in profiles):
        raise LookupError("resource profile not found")
    if len(profiles) <= 1:
        raise ValueError("the last resource profile cannot be deleted")
    if str(current.get("default_profile_id") or "").lower() == identifier:
        raise ValueError("choose another default profile before deleting this profile")
    profiles = [item for item in profiles if str(item.get("id") or "").lower() != identifier]
    return save_catalog_resource_profiles(root, game, profiles, current.get("default_profile_id"))


def set_catalog_default_profile(root: Path, game: str, profile_id: str) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    identifier = str(profile_id or "").strip().lower()
    profiles = list(current.get("profiles") or [])
    if not any(str(item.get("id") or "").lower() == identifier for item in profiles):
        raise LookupError("resource profile not found")
    return save_catalog_resource_profiles(root, game, profiles, identifier)


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "").lower()


def dispatch_catalog_resource_profiles_get(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if _role(user) not in {"admin", "controller", "operator", "customer"}:
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
    """Compatibility whole-list PUT. New UI uses item-level methods below."""
    if path != RESOURCE_PROFILES_PATH:
        return None
    role = _role(user)
    if role not in {"admin", "controller", "operator"}:
        return 403, {"error": "forbidden", "message": "catalog write access required"}
    body = payload if isinstance(payload, dict) else {}
    try:
        if role == "operator":
            current = catalog_resource_profiles(root, body.get("game"))
            if _comparable_profiles(body.get("profiles")) != _comparable_profiles(current.get("profiles")):
                return 403, {"error": "forbidden", "message": "operators can only change the default profile"}
        return 200, save_catalog_resource_profiles(root, body.get("game"), body.get("profiles"), body.get("default_profile_id"))
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível salvar os perfis de recursos."}


def dispatch_catalog_resource_profiles_post(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "profile editing requires admin or controller"}
    body = payload if isinstance(payload, dict) else {}
    try:
        return 201, create_catalog_resource_profile(root, body.get("game"), body.get("profile"))
    except (ValueError, LookupError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível criar o perfil."}


def dispatch_catalog_resource_profiles_patch(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    role = _role(user)
    body = payload if isinstance(payload, dict) else {}
    try:
        operation = str(body.get("operation") or "update").strip().lower()
        if operation == "set_default":
            if role not in {"admin", "controller", "operator"}:
                return 403, {"error": "forbidden", "message": "catalog write access required"}
            return 200, set_catalog_default_profile(root, body.get("game"), body.get("profile_id"))
        if role not in {"admin", "controller"}:
            return 403, {"error": "forbidden", "message": "profile editing requires admin or controller"}
        return 200, update_catalog_resource_profile(root, body.get("game"), body.get("profile_id"), body.get("profile"))
    except LookupError as exc:
        return 404, {"error": "not_found", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível atualizar o perfil."}


def dispatch_catalog_resource_profiles_delete(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "profile editing requires admin or controller"}
    query = parse_qs(query_string, keep_blank_values=True)
    try:
        return 200, delete_catalog_resource_profile(
            root,
            (query.get("game") or [""])[0],
            (query.get("profile_id") or [""])[0],
        )
    except LookupError as exc:
        return 404, {"error": "not_found", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível excluir o perfil."}


__all__ = [
    "RESOURCE_PROFILES_PATH",
    "catalog_resource_profiles",
    "create_catalog_resource_profile",
    "delete_catalog_resource_profile",
    "dispatch_catalog_resource_profiles_delete",
    "dispatch_catalog_resource_profiles_get",
    "dispatch_catalog_resource_profiles_patch",
    "dispatch_catalog_resource_profiles_post",
    "dispatch_catalog_resource_profiles_put",
    "save_catalog_resource_profiles",
    "set_catalog_default_profile",
    "update_catalog_resource_profile",
]
