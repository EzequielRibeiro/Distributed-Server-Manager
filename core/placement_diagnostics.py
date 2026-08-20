#!/usr/bin/env python3
"""Aggregate placement readiness diagnostics.

The functions in this module are pure domain logic. Persistence layers provide
counts describing the current infrastructure and this module turns those counts
into a stable, explainable readiness contract for CLI/API/Dashboard consumers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PLACEMENT_REASONS = frozenset(
    {
        "no_agents",
        "agent_pending",
        "missing_location",
        "missing_datacenter",
        "missing_region",
        "no_eligible_agents",
    }
)


def placement_reasons(snapshot: Mapping[str, Any]) -> list[str]:
    """Return stable blockers for an aggregate infrastructure snapshot.

    A system is placement-ready as soon as at least one Agent is eligible.
    Blockers therefore describe why *no* Agent can currently accept a new
    placement; partially configured extra Agents do not make a ready system
    globally unready.
    """
    eligible_agents = int(snapshot.get("eligible_agents", 0) or 0)
    if eligible_agents > 0:
        return []

    agents = int(snapshot.get("agents", 0) or 0)
    if agents <= 0:
        return ["no_agents"]

    reasons: list[str] = []

    if int(snapshot.get("pending_agents", 0) or 0) > 0:
        reasons.append("agent_pending")

    if int(snapshot.get("unlocated_agents", 0) or 0) > 0:
        reasons.append("missing_location")

    if int(snapshot.get("datacenters", 0) or 0) <= 0:
        reasons.append("missing_datacenter")

    if int(snapshot.get("regions", 0) or 0) <= 0:
        reasons.append("missing_region")

    reasons.append("no_eligible_agents")
    return reasons


def placement_status(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the public aggregate readiness fields for *snapshot*."""
    reasons = placement_reasons(snapshot)
    ready = int(snapshot.get("eligible_agents", 0) or 0) > 0
    return {
        "placement_ready": ready,
        "placement_reason": None if ready else reasons[0],
        "placement_reasons": reasons,
    }
