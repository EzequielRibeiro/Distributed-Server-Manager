"""Placement bridge for customer instance creation."""

from __future__ import annotations

from typing import Any

from core.placement_requirements import requirements_for_instance
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance
from region_preference_api import region_preference_for_creation


def resolve_instance_placement(
    user: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    repository,
) -> dict[str, Any]:
    """Resolve an eligible Agent for a customer instance.

    The customer never selects an Agent directly. Lifecycle, health, topology,
    capabilities, runtime compatibility, resource capacity and port capacity are
    evaluated before the normal placement scorer chooses among eligible Agents.
    """
    if (
        not user
        or str(user.get("role", "")).lower() != "customer"
        or not user.get("scope_id")
    ):
        raise PermissionError("only a scoped customer can resolve instance placement")

    payload = payload or {}
    customer_id = str(user["scope_id"]).strip()
    ph = repository.dialect.placeholder

    with repository.session() as session:
        customer = session.execute(
            "SELECT id,controller_id,status FROM customers "
            f"WHERE id={ph}",
            (customer_id,),
        ).fetchone()

    if customer is None or customer["status"] != "active":
        raise PermissionError("customer is not active")

    controller_id = str(customer["controller_id"]).strip()
    if not controller_id:
        raise PermissionError("customer has no controller")

    preference_payload = (
        payload.get("placement")
        if isinstance(payload.get("placement"), dict)
        else payload
    )
    preference = region_preference_for_creation(user, preference_payload)

    game_id = payload.get("game_id") or payload.get("game")
    runtime_id = payload.get("runtime_id") or payload.get("runtime")
    resources = payload.get("resources") if isinstance(payload.get("resources"), dict) else None
    requirements = requirements_for_instance(
        game_id=game_id,
        runtime_id=runtime_id,
        resources=resources,
    )

    decision = choose_agent_for_instance(
        repository.backend,
        controller_id=controller_id,
        preferred_region_id=preference["region_id"],
        allow_cross_region=bool(preference["allow_cross_region"]),
        requirements=requirements,
    )

    if not decision.get("agent_id"):
        raise PlacementUnavailable(
            reason="no_eligible_agents",
            requested_region_id=preference["region_id"],
        )

    return {
        "controller_id": controller_id,
        "agent_id": str(decision["agent_id"]),
        "node_id": decision.get("node_id"),
        "region_id": decision.get("region_id"),
        "datacenter_id": decision.get("datacenter_id"),
        "score": decision.get("score"),
        "reason": decision.get("reason"),
        "requirements": decision.get("requirements"),
        "allow_cross_region": bool(preference["allow_cross_region"]),
    }


__all__ = ["resolve_instance_placement"]
