"""Placement orchestration for instance creation."""

from __future__ import annotations

from typing import Any

from core.placement import (
    PlacementCandidate,
    PlacementRequest,
    choose_candidate,
)
from location_repository import LocationRepository


def choose_agent_for_instance(
    backend,
    *,
    controller_id: str,
    preferred_region_id: str | None = None,
    allow_cross_region: bool = False,
    latency_ms: dict[str, float] | None = None,
    client_latitude: float | None = None,
    client_longitude: float | None = None,
) -> dict[str, Any]:
    repository = LocationRepository(backend)
    repository.initialize()

    rows = repository.candidates(
        controller_id,
        region_id=(
            preferred_region_id
            if preferred_region_id
            and not allow_cross_region
            else None
        ),
    )

    candidates = [
        PlacementCandidate(
            agent_id=row["agent_id"],
            node_id=row["node_id"],
            region_id=row["region_id"],
            datacenter_id=row["datacenter_id"],
            instance_count=int(
                row.get("instance_count", 0) or 0
            ),
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
        )
        for row in rows
    ]

    decision = choose_candidate(
        PlacementRequest(
            controller_id=controller_id,
            preferred_region_id=preferred_region_id,
            client_latitude=client_latitude,
            client_longitude=client_longitude,
            latency_ms=latency_ms,
            allow_cross_region=allow_cross_region,
        ),
        candidates,
    )

    return {
        "agent_id": decision.candidate.agent_id,
        "node_id": decision.candidate.node_id,
        "region_id": decision.candidate.region_id,
        "datacenter_id": decision.candidate.datacenter_id,
        "score": decision.score,
        "reason": decision.reason,
    }
