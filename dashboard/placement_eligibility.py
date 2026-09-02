#!/usr/bin/env python3
"""Technical Agent eligibility boundary used by placement orchestration."""

from __future__ import annotations

from typing import Any

from core.agent_eligibility import EligibilityResult, evaluate_agent_eligibility
from core.placement_requirements import PlacementRequirements
from agent_port_availability import effective_port_summary
from agent_runtime_repository import AgentRuntimeRepository


def requires_runtime_evidence(requirements: PlacementRequirements) -> bool:
    return bool(
        requirements.runtime_id
        or requirements.capabilities
        or requirements.operating_systems
        or requirements.architectures
        or requirements.java_min_major
        or requirements.java_max_major
        or requirements.ports
        or requirements.min_cpu_threads
        or requirements.min_ram_bytes
        or requirements.min_storage_free_bytes
    )


def evaluate_agent_for_placement(
    backend,
    *,
    agent_id: str,
    requirements: PlacementRequirements,
) -> EligibilityResult:
    runtime = AgentRuntimeRepository(backend).snapshot(agent_id)

    # Legacy compatibility applies only to placements with no explicit
    # technical requirements. Once a game/runtime asks for capabilities,
    # platform facts, resources or ports, the Controller requires factual
    # heartbeat evidence.
    if runtime.get("last_seen") is None and not requires_runtime_evidence(requirements):
        return EligibilityResult(True, ())

    if runtime.get("last_seen") is None:
        return EligibilityResult(False, ("runtime_inventory_missing",))

    ports = effective_port_summary(backend, agent_id)
    return evaluate_agent_eligibility(
        runtime=runtime,
        port_summary=ports,
        requirements=requirements,
    )


def eligibility_diagnostics(result: EligibilityResult) -> dict[str, Any]:
    return {
        "eligible": bool(result.eligible),
        "reasons": list(result.reasons),
    }


__all__ = [
    "eligibility_diagnostics",
    "evaluate_agent_for_placement",
    "requires_runtime_evidence",
]
