#!/usr/bin/env python3
"""Pure domain rules for Agent topology and placement readiness.

This module intentionally has no database, HTTP, dashboard or scheduler
coupling. It provides one shared source of truth for lifecycle vocabulary and
for the derived topology/placement predicates documented in Phase 1.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


AGENT_STATES = frozenset(
    {
        "pending",
        "pairing",
        "active",
        "offline",
        "disabled",
        "rejected",
    }
)

TOPOLOGY_STATES = frozenset(
    {
        "unconfigured",
        "partial",
        "ready",
    }
)

ACTIVE_STATUS = "active"


def _status(record: Mapping[str, Any] | None) -> str | None:
    """Return a normalized status from a persistence/domain record."""
    if record is None:
        return None

    value = record.get("status")
    if value is None:
        return None

    return str(value).strip().lower()


def valid_agent_state(state: str) -> bool:
    """Return whether *state* belongs to the official Agent state vocabulary."""
    return str(state).strip().lower() in AGENT_STATES


def topology_state(
    location: Mapping[str, Any] | None,
    datacenter: Mapping[str, Any] | None,
    region: Mapping[str, Any] | None,
) -> str:
    """Derive the Agent geographic topology state.

    ``unconfigured`` means no Agent Location exists. ``ready`` requires the
    complete Location -> Datacenter -> Region chain and all three records to be
    active. Every other configured-but-incomplete/non-active combination is
    ``partial``.
    """
    if location is None:
        return "unconfigured"

    if (
        datacenter is not None
        and region is not None
        and _status(location) == ACTIVE_STATUS
        and _status(datacenter) == ACTIVE_STATUS
        and _status(region) == ACTIVE_STATUS
    ):
        return "ready"

    return "partial"


def placement_ready(
    controller: Mapping[str, Any] | None,
    agent: Mapping[str, Any] | None,
    location: Mapping[str, Any] | None,
    datacenter: Mapping[str, Any] | None,
    region: Mapping[str, Any] | None,
) -> bool:
    """Return whether an Agent is eligible to enter placement candidates.

    Placement is allowed only when every required infrastructure entity exists
    and is active. The predicate is deliberately derived rather than persisted.
    """
    return (
        controller is not None
        and agent is not None
        and topology_state(location, datacenter, region) == "ready"
        and _status(controller) == ACTIVE_STATUS
        and _status(agent) == ACTIVE_STATUS
    )


def readiness_snapshot(
    controller: Mapping[str, Any] | None,
    agent: Mapping[str, Any] | None,
    location: Mapping[str, Any] | None,
    datacenter: Mapping[str, Any] | None,
    region: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return derived readiness information suitable for service/API layers."""
    topology = topology_state(location, datacenter, region)

    return {
        "topology_state": topology,
        "placement_ready": placement_ready(
            controller,
            agent,
            location,
            datacenter,
            region,
        ),
    }
