"""Allowlisted Windows game runtime profile registry."""
from __future__ import annotations
from typing import Any
from .base import GameRuntimeProfile,ProfileError
from .dayz import DayZRuntimeProfile
_PROFILES=(DayZRuntimeProfile,)
def resolve_profile(instance:dict[str,Any])->GameRuntimeProfile:
 keys={str(instance.get("game_id") or "").strip().lower(),str(instance.get("environment_id") or "").strip().lower()}
 for cls in _PROFILES:
  if any(k in {x.lower() for x in cls.game_ids} for k in keys if k):return cls()
 raise ProfileError(f"unsupported Windows runtime profile: {str(instance.get('game_id') or instance.get('environment_id') or 'unconfigured')}")
def supported_profiles()->tuple[str,...]:return tuple(sorted({x for cls in _PROFILES for x in cls.game_ids}))
__all__=["resolve_profile","supported_profiles"]
