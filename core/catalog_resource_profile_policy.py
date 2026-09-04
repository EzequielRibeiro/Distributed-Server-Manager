#!/usr/bin/env python3
"""Canonical Catalog v2 resource-profile policy."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_GAME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _game_id(value: str) -> str:
    game = str(value or "").strip().lower()
    if not _GAME_ID.fullmatch(game):
        raise ValueError("invalid game id")
    return game


def load_game_resource_profiles(root: Path, game_id: str) -> dict[str, Any]:
    root = Path(root).resolve()
    game = _game_id(game_id)
    games_root = (root / "catalog" / "v2" / "games").resolve()
    path = (games_root / game / "resource-profiles.json").resolve()

    try:
        path.relative_to(games_root)
    except ValueError as exc:
        raise ValueError("invalid resource profile catalog path") from exc

    if not path.is_file():
        return {
            "schema_version": 2,
            "kind": "GameResourceProfiles",
            "game": game,
            "default_profile_id": "",
            "profiles": [],
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid resource profile catalog for game {game!r}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"invalid resource profile catalog for game {game!r}")
    if payload.get("schema_version") != 2:
        raise ValueError(f"unsupported resource profile schema for game {game!r}")
    if payload.get("kind") != "GameResourceProfiles":
        raise ValueError(f"invalid resource profile catalog kind for game {game!r}")
    if str(payload.get("game") or "").strip().lower() != game:
        raise ValueError(f"resource profile catalog game mismatch for {game!r}")

    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError(f"resource profile catalog profiles must be a list for game {game!r}")

    ids: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            raise ValueError(f"invalid resource profile entry for game {game!r}")
        profile_id = str(item.get("id") or "").strip().lower()
        if not profile_id:
            raise ValueError(f"resource profile id is required for game {game!r}")
        if profile_id in ids:
            raise ValueError(f"duplicate resource profile {profile_id!r} for game {game!r}")
        ids.add(profile_id)

    default_id = str(payload.get("default_profile_id") or "").strip().lower()
    if profiles and (not default_id or default_id not in ids):
        raise ValueError(f"invalid default resource profile for game {game!r}")

    return payload


def resolve_catalog_resource_profile(
    *,
    root: Path,
    game_id: str,
    requested_profile_id: str | None = None,
    require_catalog: bool = False,
) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    game = _game_id(game_id)
    catalog = load_game_resource_profiles(root, game)
    profiles = [dict(item) for item in catalog.get("profiles", []) if isinstance(item, dict)]
    requested = str(requested_profile_id or "").strip().lower()

    if not profiles:
        if requested:
            raise ValueError(f"resource profile {requested!r} not found for game {game!r}")
        if require_catalog:
            raise ValueError(f"game {game!r} has no resource profiles configured")
        return None, {}, catalog

    default_id = str(catalog.get("default_profile_id") or "").strip().lower()
    resolved_id = requested or default_id
    profile = next(
        (
            item
            for item in profiles
            if str(item.get("id") or "").strip().lower() == resolved_id
        ),
        None,
    )
    if profile is None:
        raise ValueError(f"resource profile {resolved_id!r} not found for game {game!r}")

    return resolved_id, profile, catalog


__all__ = [
    "load_game_resource_profiles",
    "resolve_catalog_resource_profile",
]
