#!/usr/bin/env python3
"""Allowlisted game_id/environment_id to runtime profile registry."""

from __future__ import annotations

from typing import Any

from .base import GameRuntimeProfile, ProfileError
from .dayz import DayZRuntimeProfile
from .projectzomboid import ProjectZomboidRuntimeProfile

_PROFILE_TYPES = (DayZRuntimeProfile, ProjectZomboidRuntimeProfile)
_PROFILES: dict[str, type[GameRuntimeProfile]] = {}
for profile_type in _PROFILE_TYPES:
    for game_id in profile_type.game_ids:
        key = str(game_id).strip().lower()
        if not key or key in _PROFILES:
            raise RuntimeError(f"duplicate or invalid game runtime profile id: {key!r}")
        _PROFILES[key] = profile_type


def resolve_profile(instance: dict[str, Any]) -> GameRuntimeProfile:
    candidates = (
        str(instance.get("environment_id") or "").strip().lower(),
        str(instance.get("game_id") or "").strip().lower(),
    )
    for key in candidates:
        factory = _PROFILES.get(key)
        if factory is not None:
            return factory()
    requested = candidates[0] or candidates[1] or "unconfigured"
    raise ProfileError(f"unsupported game runtime profile: {requested}")


def supported_profiles() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))


__all__ = ["resolve_profile", "supported_profiles"]
