#!/usr/bin/env python3
"""Pure Agent eligibility evaluation for placement.

The evaluator has no database dependency.  It receives one Agent runtime
snapshot plus the authoritative port summary and decides whether the Agent can
accept a new instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.placement_requirements import PlacementRequirements


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]


def _capability_set(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = {
            str(key).strip().lower()
            for key, enabled in value.items()
            if enabled is True and str(key).strip()
        }
        runtime = value.get("runtime")
        if runtime:
            result.add(str(runtime).strip().lower())
        runtimes = value.get("runtimes")
        if isinstance(runtimes, (list, tuple, set)):
            result.update(str(item).strip().lower() for item in runtimes if str(item).strip())
        return result
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    return set()


def evaluate_agent_eligibility(
    *,
    runtime: dict[str, Any],
    port_summary: dict[str, Any],
    requirements: PlacementRequirements,
) -> EligibilityResult:
    reasons: list[str] = []

    status = str(runtime.get("status") or "").strip().lower()
    if status != "active":
        reasons.append("agent_not_active")

    health = str(runtime.get("health_status") or "offline").strip().lower()
    if health != "online":
        reasons.append("agent_not_online")

    capabilities = _capability_set(runtime.get("capabilities"))
    missing = sorted(requirements.capabilities - capabilities)
    if requirements.runtime_id and requirements.runtime_id not in capabilities:
        missing.append(requirements.runtime_id)
    if missing:
        reasons.append("missing_capabilities:" + ",".join(sorted(set(missing))))

    cpu = runtime.get("cpu") if isinstance(runtime.get("cpu"), dict) else {}
    threads = int(cpu.get("logical_cores") or 0)
    if requirements.min_cpu_threads and threads < requirements.min_cpu_threads:
        reasons.append("insufficient_cpu")

    ram = int(runtime.get("ram_total_bytes") or 0)
    if requirements.min_ram_bytes and ram < requirements.min_ram_bytes:
        reasons.append("insufficient_ram")

    storage = runtime.get("storage") if isinstance(runtime.get("storage"), dict) else {}
    free_storage = int(storage.get("root_free_bytes") or storage.get("free_bytes") or 0)
    if requirements.min_storage_free_bytes and free_storage < requirements.min_storage_free_bytes:
        reasons.append("insufficient_storage")

    ranges = port_summary.get("ranges") if isinstance(port_summary, dict) else []
    ranges = ranges if isinstance(ranges, list) else []
    for requirement in requirements.ports:
        matching = [
            item for item in ranges
            if str(item.get("protocol", "")).lower() == requirement.protocol
            and str(item.get("status", "active")).lower() == "active"
        ]
        if not matching:
            reasons.append(f"missing_{requirement.protocol}_range")
            continue
        if requirement.contiguous:
            if not any(int(item.get("largest_contiguous_available", 0) or 0) >= requirement.count for item in matching):
                reasons.append(f"insufficient_{requirement.protocol}_ports")
        elif sum(int(item.get("available", 0) or 0) for item in matching) < requirement.count:
            reasons.append(f"insufficient_{requirement.protocol}_ports")

    return EligibilityResult(not reasons, tuple(reasons))


__all__ = ["EligibilityResult", "evaluate_agent_eligibility"]
