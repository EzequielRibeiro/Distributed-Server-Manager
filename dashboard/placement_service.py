"""Placement orchestration for instance creation."""

from __future__ import annotations

from typing import Any

from core.placement import PlacementCandidate, PlacementRequest, choose_candidate
from core.placement_requirements import PlacementRequirements
from agent_runtime_repository import AgentRuntimeRepository
from location_repository import LocationRepository
from placement_eligibility import evaluate_agent_for_placement
from placement_errors import PlacementUnavailable
from placement_status_repository import PlacementStatusRepository


def _controller_agent_count(repository: LocationRepository, controller_id: str) -> int:
    ph = repository.dialect.placeholder
    with repository.session() as session:
        row = session.execute(
            f"SELECT COUNT(*) AS total FROM agents WHERE controller_id={ph}",
            (controller_id,),
        ).fetchone()
    return int(row["total"])


def _unavailable_reason(backend, *, preferred_region_id: str | None) -> str:
    snapshot = PlacementStatusRepository(backend).snapshot()
    if int(snapshot.get("eligible_agents", 0) or 0) == 0:
        return str(snapshot.get("placement_reason") or "no_eligible_agents")
    if preferred_region_id:
        return "requested_region_unavailable"
    return "no_eligible_agents"


def choose_agent_for_instance(
    backend,
    *,
    controller_id: str,
    preferred_region_id: str | None = None,
    allow_cross_region: bool = False,
    latency_ms: dict[str, float] | None = None,
    client_latitude: float | None = None,
    client_longitude: float | None = None,
    requirements: PlacementRequirements | None = None,
) -> dict[str, Any]:
    repository = LocationRepository(backend)
    repository.initialize()
    agents_evaluated = _controller_agent_count(repository, controller_id)
    requirements = requirements or PlacementRequirements()

    rows = repository.candidates(
        controller_id,
        region_id=(preferred_region_id if preferred_region_id and not allow_cross_region else None),
    )

    # Lifecycle/topology are already enforced by LocationRepository.candidates.
    # Telemetry-aware Agents must be online; legacy Agents remain compatible
    # only when no explicit technical evidence is required.
    health = AgentRuntimeRepository(backend).refresh_health(controller_id=controller_id)
    rows = [row for row in rows if health.get(str(row["agent_id"]), "online") == "online"]

    technical_rejections: dict[str, list[str]] = {}
    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        result = evaluate_agent_for_placement(
            backend,
            agent_id=str(row["agent_id"]),
            requirements=requirements,
        )
        if result.eligible:
            eligible_rows.append(row)
        else:
            technical_rejections[str(row["agent_id"])] = list(result.reasons)
    rows = eligible_rows

    if not rows:
        raise PlacementUnavailable(
            reason=_unavailable_reason(backend, preferred_region_id=preferred_region_id),
            agents_evaluated=agents_evaluated,
            requested_region_id=preferred_region_id,
        )

    candidates = [
        PlacementCandidate(
            agent_id=row["agent_id"],
            node_id=row["node_id"],
            region_id=row["region_id"],
            datacenter_id=row["datacenter_id"],
            instance_count=int(row.get("instance_count", 0) or 0),
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
        "requirements": {
            "game_id": requirements.game_id,
            "runtime_id": requirements.runtime_id,
            "capabilities": sorted(requirements.capabilities),
            "ports": [
                {
                    "protocol": item.protocol,
                    "count": item.count,
                    "contiguous": item.contiguous,
                }
                for item in requirements.ports
            ],
        },
        "technical_rejections": technical_rejections,
    }
