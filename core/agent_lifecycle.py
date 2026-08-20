#!/usr/bin/env python3
"""Pure Agent lifecycle transition rules.

This module defines the official Agent state machine without coupling it to
persistence, HTTP, pairing transport, scheduler or dashboard code. Persistence
layers may use these helpers before applying a status change.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.placement_readiness import AGENT_STATES


class InvalidAgentState(ValueError):
    """Raised when a state is outside the official Agent vocabulary."""


class InvalidAgentTransition(ValueError):
    """Raised when a lifecycle transition is not allowed."""


# Conservative lifecycle graph. Administrative reactivation of a disabled or
# rejected Agent returns it to pending so trust/pairing can be revalidated
# before the Agent becomes active again.
AGENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"pairing", "disabled", "rejected"}),
    "pairing": frozenset({"pending", "active", "disabled", "rejected"}),
    "active": frozenset({"offline", "disabled"}),
    "offline": frozenset({"active", "disabled"}),
    "disabled": frozenset({"pending"}),
    "rejected": frozenset({"pending"}),
}


@dataclass(frozen=True)
class AgentTransition:
    current: str
    target: str
    changed: bool


def normalize_agent_state(state: str) -> str:
    """Normalize and validate an Agent lifecycle state."""
    normalized = str(state).strip().lower()
    if normalized not in AGENT_STATES:
        raise InvalidAgentState(f"invalid Agent state: {state!r}")
    return normalized


def allowed_agent_transitions(state: str) -> frozenset[str]:
    """Return allowed target states for an official state."""
    return AGENT_TRANSITIONS[normalize_agent_state(state)]


def can_transition_agent(current: str, target: str) -> bool:
    """Return whether an Agent can move from *current* to *target*.

    Reapplying the same state is accepted as an idempotent no-op. This keeps
    retrying callers safe while preserving an explicit transition graph for
    real state changes.
    """
    current_state = normalize_agent_state(current)
    target_state = normalize_agent_state(target)
    return (
        current_state == target_state
        or target_state in AGENT_TRANSITIONS[current_state]
    )


def transition_agent(current: str, target: str) -> AgentTransition:
    """Validate a transition and return its normalized result."""
    current_state = normalize_agent_state(current)
    target_state = normalize_agent_state(target)

    if not can_transition_agent(current_state, target_state):
        raise InvalidAgentTransition(
            f"Agent transition not allowed: {current_state} -> {target_state}"
        )

    return AgentTransition(
        current=current_state,
        target=target_state,
        changed=current_state != target_state,
    )
