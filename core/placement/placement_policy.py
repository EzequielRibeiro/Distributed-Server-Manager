"""Generic placement policy for Capivara DSM."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Iterable


@dataclass(frozen=True)
class PlacementRequest:
    controller_id: str
    preferred_region_id: str | None = None
    client_latitude: float | None = None
    client_longitude: float | None = None
    latency_ms: dict[str, float] | None = None
    allow_cross_region: bool = False


@dataclass(frozen=True)
class PlacementCandidate:
    agent_id: str
    node_id: str
    region_id: str
    datacenter_id: str
    instance_count: int = 0
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class PlacementDecision:
    candidate: PlacementCandidate
    score: float
    reason: str


def geographic_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    earth_radius_km = 6371.0088

    phi1 = radians(float(lat1))
    phi2 = radians(float(lat2))
    d_phi = radians(float(lat2) - float(lat1))
    d_lambda = radians(float(lon2) - float(lon1))

    value = (
        sin(d_phi / 2) ** 2
        + cos(phi1)
        * cos(phi2)
        * sin(d_lambda / 2) ** 2
    )

    return 2 * earth_radius_km * asin(sqrt(value))


def _score(
    request: PlacementRequest,
    candidate: PlacementCandidate,
) -> tuple[float, str]:
    score = float(candidate.instance_count) * 5.0
    reasons = [
        f"load={candidate.instance_count}"
    ]

    if request.preferred_region_id:
        if candidate.region_id == request.preferred_region_id:
            score -= 10000.0
            reasons.append("preferred-region")
        else:
            score += 10000.0
            reasons.append("cross-region")

    latency = (request.latency_ms or {}).get(candidate.agent_id)

    if latency is not None:
        score += float(latency) * 10.0
        reasons.append(f"latency={float(latency):.2f}ms")
    elif (
        request.client_latitude is not None
        and request.client_longitude is not None
        and candidate.latitude is not None
        and candidate.longitude is not None
    ):
        distance = geographic_distance_km(
            request.client_latitude,
            request.client_longitude,
            candidate.latitude,
            candidate.longitude,
        )

        score += distance
        reasons.append(f"distance={distance:.2f}km")

    return score, ", ".join(reasons)


def choose_candidate(
    request: PlacementRequest,
    candidates: Iterable[PlacementCandidate],
) -> PlacementDecision:
    candidates = list(candidates)

    if request.preferred_region_id and not request.allow_cross_region:
        candidates = [
            item
            for item in candidates
            if item.region_id == request.preferred_region_id
        ]

    if not candidates:
        raise RuntimeError(
            "no eligible Agent satisfies the placement policy"
        )

    ranked = []

    for candidate in candidates:
        score, reason = _score(request, candidate)
        ranked.append((score, candidate.agent_id, candidate, reason))

    ranked.sort(key=lambda item: (item[0], item[1]))

    score, _, candidate, reason = ranked[0]

    return PlacementDecision(
        candidate=candidate,
        score=score,
        reason=reason,
    )
