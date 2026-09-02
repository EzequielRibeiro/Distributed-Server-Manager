#!/usr/bin/env python3
"""Catalog-driven placement requirements.

The placement core deliberately knows nothing about individual games. Runtime
catalog definitions describe how software is installed/executed and may add an
optional ``placement`` contract for requirements that cannot be inferred from
existing generic runtime fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.catalog_runtime_paths import runtime_definition_files


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
    operating_systems: frozenset[str] = field(default_factory=frozenset)
    architectures: frozenset[str] = field(default_factory=frozenset)
    java_min_major: int = 0
    java_max_major: int = 0
    ports: tuple[PortRequirement, ...] = ()
    min_cpu_threads: int = 0
    min_ram_bytes: int = 0
    min_storage_free_bytes: int = 0


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalized_values(value: Any) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(
        str(item).strip().lower()
        for item in value
        if str(item).strip()
    )


def load_runtime_definition(
    runtime_id: str | None,
    *,
    catalog_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load one RuntimeDefinition by id from canonical or legacy catalog paths."""
    wanted = str(runtime_id or "").strip()
    if not wanted:
        return None
    for path in runtime_definition_files(catalog_root):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if item.get("kind") == "RuntimeDefinition" and str(item.get("id") or "") == wanted:
            return item
    return None


def _inferred_capabilities(definition: dict[str, Any]) -> set[str]:
    capabilities: set[str] = set()
    process = definition.get("process") if isinstance(definition.get("process"), dict) else {}
    requirements = definition.get("requirements") if isinstance(definition.get("requirements"), dict) else {}
    artifact = definition.get("artifact") if isinstance(definition.get("artifact"), dict) else {}
    placement = definition.get("placement") if isinstance(definition.get("placement"), dict) else {}

    engine = str(process.get("engine") or "").strip().lower()
    operating_systems = _normalized_values(requirements.get("os"))
    if engine == "native" and operating_systems == frozenset({"linux"}):
        capabilities.add("native-linux")
    elif engine == "native" and operating_systems == frozenset({"windows"}):
        capabilities.add("native-windows")
    elif engine == "java":
        capabilities.add("java")
    elif engine in {"docker", "container"}:
        capabilities.add("docker")
    elif engine in {"wine", "wine64"}:
        capabilities.add("wine")

    if str(artifact.get("provider") or "").strip().lower() == "steam":
        capabilities.add("steamcmd")

    declared = placement.get("capabilities")
    if isinstance(declared, (list, tuple, set)):
        capabilities.update(
            str(item).strip().lower() for item in declared if str(item).strip()
        )
    return capabilities


def _port_requirements(definition: dict[str, Any]) -> tuple[PortRequirement, ...]:
    placement = definition.get("placement") if isinstance(definition.get("placement"), dict) else {}
    declared = placement.get("ports")
    if isinstance(declared, list):
        result = []
        for item in declared:
            if not isinstance(item, dict):
                continue
            protocol = str(item.get("protocol") or "").strip().lower()
            if protocol not in {"tcp", "udp"}:
                continue
            result.append(PortRequirement(protocol, max(1, _positive_int(item.get("count"))), bool(item.get("contiguous"))))
        return tuple(result)

    network = definition.get("network") if isinstance(definition.get("network"), dict) else {}
    ports = network.get("ports") if isinstance(network.get("ports"), list) else []
    protocols = {
        str(item.get("protocol") or "").strip().lower()
        for item in ports if isinstance(item, dict)
    }
    protocols &= {"tcp", "udp"}
    if not protocols:
        return ()

    allocation = str(network.get("allocation") or "").strip().lower()
    block_size = _positive_int(network.get("block_size"))
    if allocation == "block" and block_size:
        return tuple(PortRequirement(protocol, block_size, True) for protocol in sorted(protocols))

    return tuple(
        PortRequirement(protocol, sum(1 for item in ports if isinstance(item, dict) and str(item.get("protocol") or "").strip().lower() == protocol), False)
        for protocol in sorted(protocols)
    )


def requirements_from_runtime_definition(
    definition: dict[str, Any] | None,
    *,
    resources: dict[str, Any] | None = None,
) -> PlacementRequirements:
    definition = definition if isinstance(definition, dict) else {}
    resource = resources if isinstance(resources, dict) else {}
    requirements = definition.get("requirements") if isinstance(definition.get("requirements"), dict) else {}
    java = requirements.get("java") if isinstance(requirements.get("java"), dict) else {}
    placement = definition.get("placement") if isinstance(definition.get("placement"), dict) else {}
    minimums = placement.get("resources") if isinstance(placement.get("resources"), dict) else {}
    runtime_capability = str(placement.get("runtime") or "").strip().lower() or None
    capabilities = _inferred_capabilities(definition)
    if runtime_capability:
        capabilities.add(runtime_capability)
    java_min = _positive_int(java.get("min"))
    java_max = _positive_int(java.get("max"))
    return PlacementRequirements(
        game_id=str(definition.get("game") or "").strip().lower() or None,
        runtime_id=runtime_capability,
        capabilities=frozenset(capabilities),
        operating_systems=_normalized_values(requirements.get("os")),
        architectures=_normalized_values(requirements.get("architectures")),
        java_min_major=java_min,
        java_max_major=java_max,
        ports=_port_requirements(definition),
        min_cpu_threads=_positive_int(resource.get("cpu_threads") or resource.get("min_cpu_threads") or minimums.get("cpu_threads")),
        min_ram_bytes=_positive_int(resource.get("ram_bytes") or resource.get("min_ram_bytes") or minimums.get("ram_bytes")),
        min_storage_free_bytes=_positive_int(resource.get("storage_bytes") or resource.get("min_storage_free_bytes") or minimums.get("storage_bytes")),
    )


def requirements_for_instance(
    *,
    game_id: str | None,
    runtime_id: str | None = None,
    resources: dict[str, Any] | None = None,
    catalog_root: Path | None = None,
) -> PlacementRequirements:
    definition = load_runtime_definition(runtime_id, catalog_root=catalog_root)
    result = requirements_from_runtime_definition(definition, resources=resources)
    if result.game_id is not None:
        return result
    return PlacementRequirements(
        game_id=str(game_id or "").strip().lower() or None,
        min_cpu_threads=result.min_cpu_threads,
        min_ram_bytes=result.min_ram_bytes,
        min_storage_free_bytes=result.min_storage_free_bytes,
    )


__all__ = [
    "PlacementRequirements",
    "PortRequirement",
    "load_runtime_definition",
    "requirements_for_instance",
    "requirements_from_runtime_definition",
]
