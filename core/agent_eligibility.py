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


def _structured_capabilities(runtime: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    capabilities = runtime.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    platform = capabilities.get("platform")
    platform = platform if isinstance(platform, dict) else {}
    java_status = capabilities.get("java_status")
    java_status = java_status if isinstance(java_status, dict) else {}
    return platform, java_status


def _major(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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

    capability_payload = runtime.get("capabilities")
    capabilities = _capability_set(capability_payload)
    missing = sorted(requirements.capabilities - capabilities)
    if requirements.runtime_id and requirements.runtime_id not in capabilities:
        missing.append(requirements.runtime_id)
    if missing:
        reasons.append("missing_capabilities:" + ",".join(sorted(set(missing))))

    platform, java_status = _structured_capabilities(runtime)
    if requirements.operating_systems:
        operating_system = str(platform.get("os") or "").strip().lower()
        if not operating_system:
            reasons.append("platform_os_missing")
        elif operating_system not in requirements.operating_systems:
            reasons.append("unsupported_platform_os")

    if requirements.architectures:
        architecture = str(platform.get("architecture") or "").strip().lower()
        if not architecture:
            reasons.append("platform_architecture_missing")
        elif architecture not in requirements.architectures:
            reasons.append("unsupported_platform_architecture")

    if requirements.java_min_major or requirements.java_max_major:
        java_major = _major(java_status.get("major"))
        if not java_major:
            reasons.append("java_version_missing")
        else:
            if requirements.java_min_major and java_major < requirements.java_min_major:
                reasons.append("java_version_too_old")
            if requirements.java_max_major and java_major > requirements.java_max_major:
                reasons.append("java_version_too_new")

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
