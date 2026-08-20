"""Domain errors raised by instance placement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlacementUnavailable(RuntimeError):
    """Placement could not select an eligible Agent for a request.

    The exception contains internal diagnostic context for logging. HTTP layers
    must never serialize these details directly to customers.
    """

    reason: str = "no_eligible_agents"
    agents_evaluated: int = 0
    requested_region_id: str | None = None

    def __str__(self) -> str:
        return "no eligible Agent is available for placement"


__all__ = ["PlacementUnavailable"]
