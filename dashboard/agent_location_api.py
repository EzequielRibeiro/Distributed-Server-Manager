"""RBAC-aware Agent geographic location administration."""

from __future__ import annotations

from typing import Any

from infrastructure_repository import InfrastructureRepository
from location_repository import LocationRepository


def _location_repository(backend) -> LocationRepository:
    repository = LocationRepository(backend)
    repository.initialize()
    return repository


def _infrastructure_repository(backend) -> InfrastructureRepository:
    return InfrastructureRepository(backend)


def _agent_for_user(
    user: dict[str, Any] | None,
    backend,
    agent_id: str,
) -> dict[str, Any]:
    if not user:
        raise PermissionError("authentication required")

    identifier = str(agent_id).strip()
    if not identifier:
        raise ValueError("agent_id is required")

    repository = _infrastructure_repository(backend)
    agents = repository.agents()

    agent = next(
        (
            item
            for item in agents
            if str(item["id"]) == identifier
        ),
        None,
    )

    if agent is None:
        raise ValueError("agent not found")

    role = str(user.get("role", "")).strip().lower()

    if role == "admin":
        return agent

    if role == "controller":
        scope_id = str(user.get("scope_id", "")).strip()

        if scope_id and scope_id == str(agent["controller_id"]):
            return agent

        raise PermissionError("agent is outside user scope")

    raise PermissionError("agent administration is not permitted")


def _datacenter(
    backend,
    datacenter_id: str,
) -> dict[str, Any]:
    identifier = str(datacenter_id).strip()

    if not identifier:
        raise ValueError("datacenter_id is required")

    repository = _infrastructure_repository(backend)

    datacenter = next(
        (
            item
            for item in repository.datacenters()
            if str(item["id"]) == identifier
        ),
        None,
    )

    if datacenter is None:
        raise ValueError("datacenter not found")

    if str(datacenter.get("status", "")).lower() != "active":
        raise ValueError("datacenter is not active")

    return datacenter


def _optional_float(
    payload: dict[str, Any],
    name: str,
) -> float | None:
    value = payload.get(name)

    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def set_agent_location_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assign or update the geographic location of one Agent."""

    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    agent_id = str(payload.get("agent_id", "")).strip()
    datacenter_id = str(payload.get("datacenter_id", "")).strip()

    agent = _agent_for_user(
        user,
        backend,
        agent_id,
    )

    datacenter = _datacenter(
        backend,
        datacenter_id,
    )

    latitude = _optional_float(payload, "latitude")
    longitude = _optional_float(payload, "longitude")

    if latitude is not None and not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")

    if longitude is not None and not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")

    public_host = payload.get("public_host")
    if public_host is not None:
        public_host = str(public_host).strip() or None

    status = str(
        payload.get("status", "active")
    ).strip().lower()

    if status not in {"active", "disabled"}:
        raise ValueError("invalid location status")

    repository = _location_repository(backend)

    repository.upsert_agent_location(
        agent_id=agent["id"],
        datacenter_id=datacenter["id"],
        latitude=latitude,
        longitude=longitude,
        public_host=public_host,
        status=status,
    )

    return {
        "agent_id": agent["id"],
        "controller_id": agent["controller_id"],
        "datacenter_id": datacenter["id"],
        "region_id": datacenter["region_id"],
        "latitude": latitude,
        "longitude": longitude,
        "public_host": public_host,
        "status": status,
    }
