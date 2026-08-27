"""Placement bridge for Customer instance creation."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from core.placement_requirements import requirements_for_instance
from customer_reference import resolve_customer_reference
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance
from region_preference_api import region_preference_for_creation
from universal_event_repository import UniversalEventRepository


def _customer_id(user: dict[str, Any]) -> int:
    if user.get("customer_id") is not None:
        return resolve_customer_reference(user["customer_id"])
    public = user.get("customer_code") or user.get("scope_id")
    if not public:
        raise PermissionError("only a scoped customer can resolve instance placement")
    return resolve_customer_reference(public, public_only=True)


def _event_value(value: Any) -> Any:
    """Convert placement domain values into database-event-safe primitives."""
    if is_dataclass(value):
        return _event_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _event_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_event_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _region_latency(payload: dict[str, Any]) -> dict[str, float]:
    """Accept customer-safe latency observations keyed only by public region id."""
    placement = payload.get("placement") if isinstance(payload.get("placement"), dict) else payload
    raw = placement.get("region_latency_ms")
    if not isinstance(raw, dict):
        return {}
    values: dict[str, float] = {}
    for key, value in raw.items():
        region_id = str(key or "").strip()
        if not region_id:
            continue
        try:
            latency = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= latency <= 5000.0:
            values[region_id] = latency
    return values


def _publish_placement_event(
    repository,
    *,
    event_type: str,
    severity: str,
    controller_id: str,
    customer_id: int,
    customer_code: str,
    requested_region_id: str | None,
    allow_cross_region: bool,
    game_id: Any,
    runtime_id: Any,
    requirements: Any,
    decision: dict[str, Any] | None = None,
    message: str | None = None,
) -> None:
    decision = dict(decision or {})
    UniversalEventRepository(repository.backend).publish(
        {
            "event_type": event_type,
            "source": "controller.placement",
            "source_id": controller_id,
            "severity": severity,
            "agent_id": decision.get("agent_id"),
            "actor_type": "customer",
            "actor_id": customer_code,
            "data": {
                "controller_id": controller_id,
                "customer_id": customer_id,
                "customer_code": customer_code,
                "requested_region_id": requested_region_id,
                "allow_cross_region": allow_cross_region,
                "game_id": _event_value(game_id),
                "runtime_id": _event_value(runtime_id),
                "requirements": _event_value(requirements),
                "selected_region_id": decision.get("region_id"),
                "selected_datacenter_id": decision.get("datacenter_id"),
                "selected_node_id": decision.get("node_id"),
                "score": decision.get("score"),
                "reason": _event_value(decision.get("reason")),
                "latency_ms": decision.get("latency_ms"),
                "latency_source": decision.get("latency_source"),
                "distance_km": decision.get("distance_km"),
                "eligible_agents": 1 if decision.get("agent_id") else 0,
                "message": message,
            },
        }
    )


def resolve_instance_placement(
    user: dict[str, Any] | None,
    payload: dict[str, Any] | None,
    repository,
) -> dict[str, Any]:
    """Resolve an eligible Agent for a Customer instance."""
    if not user or str(user.get("role", "")).lower() != "customer":
        raise PermissionError("only a scoped customer can resolve instance placement")

    payload = payload or {}
    customer_id = _customer_id(user)
    ph = repository.dialect.placeholder

    with repository.session() as session:
        customer = session.execute(
            "SELECT id,customer_code,controller_id,status FROM customers "
            f"WHERE id={ph}",
            (customer_id,),
        ).fetchone()

    if customer is None or customer["status"] != "active":
        raise PermissionError("customer is not active")

    controller_id = str(customer["controller_id"]).strip()
    if not controller_id:
        raise PermissionError("customer has no controller")
    customer_code = str(customer["customer_code"])

    preference_payload = (
        payload.get("placement")
        if isinstance(payload.get("placement"), dict)
        else payload
    )
    preference = region_preference_for_creation(user, preference_payload)
    region_latency_ms = _region_latency(payload)

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
        region_latency_ms=region_latency_ms,
        requirements=requirements,
    )

    if not decision.get("agent_id"):
        _publish_placement_event(
            repository,
            event_type="PLACEMENT_UNAVAILABLE",
            severity="critical",
            controller_id=controller_id,
            customer_id=customer_id,
            customer_code=customer_code,
            requested_region_id=preference["region_id"],
            allow_cross_region=bool(preference["allow_cross_region"]),
            game_id=game_id,
            runtime_id=runtime_id,
            requirements=requirements,
            decision=decision,
            message="Nenhum Agent elegível está disponível para a localização solicitada.",
        )
        raise PlacementUnavailable(
            reason="no_eligible_agents",
            requested_region_id=preference["region_id"],
        )

    _publish_placement_event(
        repository,
        event_type="PLACEMENT_SELECTED",
        severity="info",
        controller_id=controller_id,
        customer_id=customer_id,
        customer_code=customer_code,
        requested_region_id=preference["region_id"],
        allow_cross_region=bool(preference["allow_cross_region"]),
        game_id=game_id,
        runtime_id=runtime_id,
        requirements=requirements,
        decision=decision,
        message="Agent elegível selecionado pelo Placement Engine.",
    )

    return {
        "customer_id": customer_id,
        "customer_code": customer_code,
        "controller_id": controller_id,
        "agent_id": str(decision["agent_id"]),
        "node_id": decision.get("node_id"),
        "region_id": decision.get("region_id"),
        "datacenter_id": decision.get("datacenter_id"),
        "score": decision.get("score"),
        "reason": decision.get("reason"),
        "latency_ms": decision.get("latency_ms"),
        "latency_source": decision.get("latency_source"),
        "distance_km": decision.get("distance_km"),
        "requirements": decision.get("requirements"),
        "allow_cross_region": bool(preference["allow_cross_region"]),
    }


__all__ = ["resolve_instance_placement"]
