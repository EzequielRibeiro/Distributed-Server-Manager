#!/usr/bin/env python3
"""Pure Agent lifecycle transition rules."""

from __future__ import annotations

from dataclasses import dataclass

from core.placement_readiness import AGENT_STATES


class InvalidAgentState(ValueError):
    """Raised when a state is outside the official Agent vocabulary."""


class InvalidAgentTransition(ValueError):
    """Raised when a lifecycle transition is not allowed."""


# ``offline`` remains a supported lifecycle value for compatibility/manual
# administration, but heartbeat health is maintained separately and MUST NOT
# write agents.status.
AGENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "discovered": frozenset({"pending", "disabled", "rejected", "decommissioned"}),
    "pending": frozenset({"pairing", "disabled", "rejected", "decommissioned"}),
    "pairing": frozenset({"pending", "active", "disabled", "rejected", "decommissioned"}),
    "active": frozenset({"offline", "disabled", "decommissioned"}),
    "offline": frozenset({"active", "disabled", "decommissioned"}),
    "disabled": frozenset({"pending", "decommissioned"}),
    "rejected": frozenset({"pending", "decommissioned"}),
    "decommissioned": frozenset(),
}


@dataclass(frozen=True)
class AgentTransition:
    current: str
    target: str
    changed: bool


def normalize_agent_state(state: str) -> str:
    normalized = str(state).strip().lower()
    if normalized not in AGENT_STATES:
        raise InvalidAgentState(f"invalid Agent state: {state!r}")
    return normalized


def allowed_agent_transitions(state: str) -> frozenset[str]:
    return AGENT_TRANSITIONS[normalize_agent_state(state)]


def can_transition_agent(current: str, target: str) -> bool:
    current_state = normalize_agent_state(current)
    target_state = normalize_agent_state(target)
    return current_state == target_state or target_state in AGENT_TRANSITIONS[current_state]


def transition_agent(current: str, target: str) -> AgentTransition:
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
