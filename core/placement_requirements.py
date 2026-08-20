#!/usr/bin/env python3
"""Placement requirements shared by capabilities, resources and port filters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PortRequirement:
    protocol: str
    count: int = 1
    contiguous: bool = False


@dataclass(frozen=True)
class PlacementRequirements:
    game_id: str | None = None
    runtime_id: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    ports: tuple[PortRequirement, ...] = ()
    min_cpu_threads: int = 0
    min_ram_bytes: int = 0
    min_storage_free_bytes: int = 0


# These entries describe technical execution requirements, not sizing advice.
# Resource thresholds remain request/catalog driven because memory/storage needs
# vary by game version, maps, mods and server configuration.
_GAME_PROFILES: dict[str, dict[str, Any]] = {
    "dayz": {
        "runtime_id": "native-linux",
        "capabilities": {"native-linux", "steamcmd", "dayz"},
        # DayZ policy: one 10-port UDP allocation block per instance.
        "ports": (PortRequirement("udp", 10, True),),
    },
    "minecraft-java": {
        "runtime_id": "native-linux",
        "capabilities": {"native-linux", "minecraft-java"},
        "ports": (PortRequirement("tcp", 1, False),),
    },
    "minecraft": {
        "runtime_id": "native-linux",
        "capabilities": {"native-linux", "minecraft-java"},
        "ports": (PortRequirement("tcp", 1, False),),
    },
    "minecraft-bedrock": {
        "runtime_id": "native-linux",
        "capabilities": {"native-linux", "minecraft-bedrock"},
        "ports": (PortRequirement("udp", 1, False),),
    },
}


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def requirements_for_instance(
    *,
    game_id: str | None,
    runtime_id: str | None = None,
    resources: dict[str, Any] | None = None,
) -> PlacementRequirements:
    game = str(game_id or "").strip().lower() or None
    profile = dict(_GAME_PROFILES.get(game or "", {}))
    resource = resources if isinstance(resources, dict) else {}
    runtime = str(runtime_id or profile.get("runtime_id") or "").strip().lower() or None
    capabilities = frozenset(str(item).strip().lower() for item in profile.get("capabilities", set()) if str(item).strip())
    return PlacementRequirements(
        game_id=game,
        runtime_id=runtime,
        capabilities=capabilities,
        ports=tuple(profile.get("ports", ())),
        min_cpu_threads=_positive_int(resource.get("cpu_threads") or resource.get("min_cpu_threads")),
        min_ram_bytes=_positive_int(resource.get("ram_bytes") or resource.get("min_ram_bytes")),
        min_storage_free_bytes=_positive_int(resource.get("storage_bytes") or resource.get("min_storage_free_bytes")),
    )


__all__ = ["PlacementRequirements", "PortRequirement", "requirements_for_instance"]
