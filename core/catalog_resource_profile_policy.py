#!/usr/bin/env python3
"""Canonical Catalog v2 resource-profile policy."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_GAME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def normalize_game_id(value: str) -> str:
    game = str(value or "").strip().lower()
    if not _GAME_ID.fullmatch(game):
        raise ValueError("invalid game id")
    return game


def normalize_resource_profile(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("invalid resource profile")

    identifier = str(item.get("id") or "").strip().lower()
    name = str(item.get("name") or "").strip()

    if not _PROFILE_ID.fullmatch(identifier):
        raise ValueError("resource profile ID must be valid")
    if not name:
        raise ValueError("resource profile name is required")

    try:
        memory_mb = int(item.get("memory_mb"))
        storage_mb = int(item.get("storage_mb"))
        raw_cpu_cores = item.get("cpu_cores")
        cpu_cores = (
            float(raw_cpu_cores)
            if raw_cpu_cores not in (None, "")
            else None
        )
        swap_mb = int(item.get("swap_mb") or 0)
        pids_limit = int(item.get("pids_limit") or 512)
    except (TypeError, ValueError) as exc:
        raise ValueError("resource profile values must be numeric") from exc

    if (
        memory_mb < 256
        or storage_mb < 1024
        or (cpu_cores is not None and cpu_cores <= 0)
        or swap_mb < 0
        or pids_limit < 1
    ):
        raise ValueError("resource profile values are outside the allowed range")

    profile = {
        "id": identifier,
        "name": name,
        "description": str(item.get("description") or "").strip(),
        "memory_mb": memory_mb,
        "storage_mb": storage_mb,
        "swap_mb": swap_mb,
        "pids_limit": pids_limit,
    }
    if cpu_cores is not None:
        profile["cpu_cores"] = cpu_cores
    return profile


def _catalog_paths(root: Path, game: str) -> tuple[Path, Path]:
    root = Path(root).resolve()

    overrides_root = (root / "config" / "catalog-resource-profiles").resolve()
    override_path = (overrides_root / f"{game}.json").resolve()

    games_root = (root / "catalog" / "v2" / "games").resolve()
    catalog_path = (games_root / game / "resource-profiles.json").resolve()

    try:
        override_path.relative_to(overrides_root)
        catalog_path.relative_to(games_root)
    except ValueError as exc:
        raise ValueError("invalid resource profile catalog path") from exc

    return override_path, catalog_path


def _empty_catalog(game: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "GameResourceProfiles",
        "game": game,
        "default_profile_id": None,
        "profiles": [],
    }


def load_game_resource_profiles(root: Path, game_id: str) -> dict[str, Any]:
    """Load effective profiles.

    Precedence:
      1. config/catalog-resource-profiles/<game>.json
      2. catalog/v2/games/<game>/resource-profiles.json
    """
    game = normalize_game_id(game_id)
    override_path, catalog_path = _catalog_paths(root, game)

    path = override_path if override_path.is_file() else catalog_path
    if not path.is_file():
        return _empty_catalog(game)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"invalid resource profile catalog for game {game!r}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(f"invalid resource profile catalog for game {game!r}")
    if payload.get("schema_version") != 2:
        raise ValueError(f"unsupported resource profile schema for game {game!r}")
    if payload.get("kind") != "GameResourceProfiles":
        raise ValueError(f"invalid resource profile catalog kind for game {game!r}")
    if str(payload.get("game") or "").strip().lower() != game:
        raise ValueError(f"resource profile catalog game mismatch for {game!r}")

    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list):
        raise ValueError(
            f"resource profile catalog profiles must be a list for game {game!r}"
        )

    profiles: list[dict[str, Any]] = []
    identifiers: set[str] = set()

    for raw_profile in raw_profiles:
        profile = normalize_resource_profile(raw_profile)
        profile_id = profile["id"]
        if profile_id in identifiers:
            raise ValueError(
                f"duplicate resource profile {profile_id!r} for game {game!r}"
            )
        identifiers.add(profile_id)
        profiles.append(profile)

    default_id = str(payload.get("default_profile_id") or "").strip().lower()
    if profiles and (not default_id or default_id not in identifiers):
        raise ValueError(f"invalid default resource profile for game {game!r}")
    if not profiles:
        default_id = ""

    return {
        "schema_version": 2,
        "kind": "GameResourceProfiles",
        "game": game,
        "default_profile_id": default_id or None,
        "profiles": profiles,
    }


def resolve_catalog_resource_profile(
    *,
    root: Path,
    game_id: str,
    requested_profile_id: str | None = None,
    require_catalog: bool = False,
) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    game = normalize_game_id(game_id)
    catalog = load_game_resource_profiles(root, game)
    profiles = list(catalog.get("profiles") or [])
    requested = str(requested_profile_id or "").strip().lower()

    if requested and not _PROFILE_ID.fullmatch(requested):
        raise ValueError("resource profile ID must be valid")

    if not profiles:
        if requested:
            raise ValueError(
                f"resource profile {requested!r} not found for game {game!r}"
            )
        if require_catalog:
            raise ValueError(
                f"game {game!r} has no resource profiles configured"
            )
        return None, {}, catalog

    default_id = str(catalog.get("default_profile_id") or "").strip().lower()
    resolved_id = requested or default_id

    profile = next(
        (
            dict(item)
            for item in profiles
            if str(item.get("id") or "").strip().lower() == resolved_id
        ),
        None,
    )
    if profile is None:
        raise ValueError(
            f"resource profile {resolved_id!r} not found for game {game!r}"
        )

    return resolved_id, profile, catalog


__all__ = [
    "load_game_resource_profiles",
    "normalize_game_id",
    "normalize_resource_profile",
    "resolve_catalog_resource_profile",
]
