#!/usr/bin/env python3
"""Read-only HTTP contract for game resource profiles stored in Catalog v2."""
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
    path = (root / "catalog" / "v2" / "games" / game / "resource-profiles.json").resolve()
    games_root = (root / "catalog" / "v2" / "games").resolve()
    try:
        path.relative_to(games_root)
    except ValueError as exc:
        raise ValueError("invalid catalog path") from exc
    if not path.is_file():
        return {"schema_version": 2, "kind": "GameResourceProfiles", "game": game, "profiles": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "GameResourceProfiles" or payload.get("game") != game:
        raise RuntimeError("invalid resource profile catalog")
    return payload


def dispatch_catalog_resource_profiles_get(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if not user or str(user.get("role") or "").lower() not in {"admin", "controller", "operator"}:
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


__all__ = ["RESOURCE_PROFILES_PATH", "catalog_resource_profiles", "dispatch_catalog_resource_profiles_get"]
