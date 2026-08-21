"""Game-specific translation into game-agnostic runtime specifications."""

from .base import GameRuntimeProfile, ProfileError
from .registry import resolve_profile, supported_profiles

__all__ = ["GameRuntimeProfile", "ProfileError", "resolve_profile", "supported_profiles"]
