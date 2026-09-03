#!/usr/bin/env python3
"""Canonical effective resource policy shared by Controller placement and Agents.

P0-E defines one normalized resource vocabulary. It intentionally does not
implement SYSTEM/CONTRACT/CUSTOMER precedence; that belongs to P0-G. Callers
must resolve the source policy before passing it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EffectiveResourcePolicy:
    cpu_cores: float = 0.0
    memory_bytes: int = 0
    storage_bytes: int = 0
    swap_bytes: int = 0
    pids_limit: int = 0
    player_limit: int = 0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "cpu_cores": self.cpu_cores,
            "memory_bytes": self.memory_bytes,
            "storage_bytes": self.storage_bytes,
            "swap_bytes": self.swap_bytes,
            "pids_limit": self.pids_limit,
            "player_limit": self.player_limit,
        }

    def placement_resources(self) -> dict[str, int | float]:
        """Translate the effective policy to placement minimum vocabulary."""
        result: dict[str, int | float] = {}
        if self.cpu_cores > 0:
            result["cpu_cores"] = self.cpu_cores
            result["cpu_threads"] = _ceil_positive(self.cpu_cores)
        if self.memory_bytes > 0:
            result["ram_bytes"] = self.memory_bytes
        if self.storage_bytes > 0:
            result["storage_bytes"] = self.storage_bytes
        return result

    def agent_resources(self) -> dict[str, int | float]:
        """Translate only enforceable configured limits to Agent vocabulary.

        Swap remains part of the canonical policy, but current Linux and Windows
        runtime reconcilers do not enforce it. It must not be advertised as an
        applied runtime limit until that enforcement exists.
        """
        result: dict[str, int | float] = {}
        if self.cpu_cores > 0:
            result["cpu_limit_cores"] = self.cpu_cores
        if self.memory_bytes > 0:
            result["memory_limit_bytes"] = self.memory_bytes
        if self.storage_bytes > 0:
            result["storage_limit_bytes"] = self.storage_bytes
        if self.pids_limit > 0:
            result["pids_limit"] = self.pids_limit
        if self.player_limit > 0:
            result["player_limit"] = self.player_limit
        return result


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _positive_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _ceil_positive(value: Any) -> int:
    numeric = _positive_float(value)
    whole = int(numeric)
    return whole if numeric == whole else whole + 1


def _bytes(primary: Any, *, mb: Any = None) -> int:
    direct = _positive_int(primary)
    if direct:
        return direct
    megabytes = _positive_int(mb)
    return megabytes * 1024 * 1024 if megabytes else 0


def normalize_resource_policy(value: dict[str, Any] | None) -> EffectiveResourcePolicy:
    """Normalize Catalog, contract, workspace or legacy Agent dictionaries.

    Canonical byte/limit keys win over compatibility MB/profile aliases when
    both are present. The result contains no unit ambiguity.
    """
    source = value if isinstance(value, dict) else {}
    return EffectiveResourcePolicy(
        cpu_cores=_positive_float(source.get("cpu_limit_cores") or source.get("cpu_cores")),
        memory_bytes=_bytes(source.get("memory_limit_bytes") or source.get("memory_bytes"), mb=source.get("memory_mb")),
        storage_bytes=_bytes(source.get("storage_limit_bytes") or source.get("storage_bytes"), mb=source.get("storage_mb")),
        swap_bytes=_bytes(source.get("swap_limit_bytes") or source.get("swap_bytes"), mb=source.get("swap_mb")),
        pids_limit=_positive_int(source.get("pids_limit")),
        player_limit=_positive_int(source.get("player_limit")),
    )


def canonical_resource_dict(value: dict[str, Any] | None) -> dict[str, int | float]:
    return normalize_resource_policy(value).as_dict()


__all__ = [
    "EffectiveResourcePolicy",
    "canonical_resource_dict",
    "normalize_resource_policy",
]
