#!/usr/bin/env python3
"""Pure domain rules for Agent topology and placement readiness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AGENT_STATES = frozenset(
    {
        "discovered",
        "pending",
        "pairing",
        "active",
        "offline",
        "disabled",
        "rejected",
    }
)

TOPOLOGY_STATES = frozenset({"unconfigured", "partial", "ready"})
ACTIVE_STATUS = "active"


def _status(record: Mapping[str, Any] | None) -> str | None:
    if record is None:
        return None
    value = record.get("status")
    if value is None:
        return None
    return str(value).strip().lower()


def valid_agent_state(state: str) -> bool:
    return str(state).strip().lower() in AGENT_STATES


def topology_state(
    location: Mapping[str, Any] | None,
    datacenter: Mapping[str, Any] | None,
    region: Mapping[str, Any] | None,
) -> str:
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
