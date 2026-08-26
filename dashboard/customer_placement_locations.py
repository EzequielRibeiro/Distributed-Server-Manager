#!/usr/bin/env python3
"""Customer-safe geographic placement discovery and recommendation."""
from __future__ import annotations

import math
from typing import Any

from core.placement_requirements import requirements_for_instance
from location_repository import LocationRepository
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _distance_latency_ms(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> int | None:
    """Conservative RTT estimate from geographic distance, explicitly not a probe."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    km = 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    # Fiber paths are longer than great-circle distance.  A 10 ms floor keeps
    # the value clearly in the realm of an estimate rather than a fake probe.
    return max(10, int(round((km * 1.35) / 100.0)))


def _customer_controller(user: dict[str, Any] | None, repository: LocationRepository) -> str:
    if not user or str(user.get("role") or "").strip().lower() != "customer" or not user.get("scope_id"):
        raise PermissionError("customer authentication required")
    ph = repository.dialect.placeholder
    with repository.session() as session:
        row = session.execute(
            "SELECT controller_id,status FROM customers WHERE id=" + ph,
            (str(user["scope_id"]),),
        ).fetchone()
    if row is None or str(row["status"] or "").strip().lower() != "active":
        raise PermissionError("customer is not active")
    return str(row["controller_id"] or "").strip()


def customer_placement_locations(
    user: dict[str, Any] | None,
    backend,
    *,
    game_id: str | None = None,
    runtime_id: str | None = None,
    client_latitude: float | None = None,
    client_longitude: float | None = None,
    catalog_root=None,
) -> dict[str, Any]:
    repository = LocationRepository(backend)
    repository.initialize()
    controller_id = _customer_controller(user, repository)
    requirements = requirements_for_instance(
        game_id=game_id,
        runtime_id=runtime_id,
        catalog_root=catalog_root,
    )

    regions = {str(item["id"]): dict(item) for item in repository.regions()}
    visible_region_ids = sorted({str(row["region_id"]) for row in repository.candidates(controller_id)})
    locations: list[dict[str, Any]] = []

    for region_id in visible_region_ids:
        region = regions.get(region_id, {})
        latitude = _number(region.get("latitude"))
        longitude = _number(region.get("longitude"))
        latency = _distance_latency_ms(client_latitude, client_longitude, latitude, longitude)
        try:
            decision = choose_agent_for_instance(
                backend,
                controller_id=controller_id,
                preferred_region_id=region_id,
                allow_cross_region=False,
                client_latitude=client_latitude,
                client_longitude=client_longitude,
                requirements=requirements,
            )
            available = True
            score = float(decision.get("score") or 0.0)
        except PlacementUnavailable:
            available = False
            score = -1.0

        locations.append({
            "location_id": "region:" + region_id,
            "region_id": region_id,
            "name": str(region.get("name") or region_id),
            "country_code": str(region.get("country_code") or "").upper() or None,
            "availability": "available" if available else "unavailable",
            "capacity": "available" if available else "unavailable",
            "latency": {"kind": "estimated", "value_ms": latency},
            "score": score,
            "recommended": False,
        })

    available = [item for item in locations if item["availability"] == "available"]
    available.sort(key=lambda item: ((item["latency"]["value_ms"] is None), item["latency"]["value_ms"] or 0, -item["score"]))
    if available:
        best = available[0]
        best["recommended"] = True
        best["recommendation"] = "server_recommended"
    for item in locations:
        if "recommendation" not in item:
            if item["availability"] != "available":
                item["recommendation"] = "unavailable"
            elif item["latency"]["value_ms"] is not None and item["latency"]["value_ms"] >= 120:
                item["recommendation"] = "higher_latency"
            else:
                item["recommendation"] = "good_option"

    locations.sort(key=lambda item: (not item["recommended"], item["availability"] != "available", item["latency"]["value_ms"] is None, item["latency"]["value_ms"] or 0, item["name"]))
    return {
        "locations": locations,
        "latency_kind": "estimated",
        "selection_scope": "region",
    }


__all__ = ["customer_placement_locations"]
