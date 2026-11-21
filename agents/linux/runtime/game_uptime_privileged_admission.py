#!/usr/bin/env python3
"""DSM #928: fail-closed admission for NEW privileged Agent mutations only.

This is not an in-flight fence, distributed ACK, transaction lease, or
authorization for update.sh --no-drain. It does not alter the hold reader.
"""
from __future__ import annotations

from game_uptime_maintenance_hold import observe


class PrivilegedMutationHold(RuntimeError):
    """A root-owned hold/journal or invalid evidence forbids new work."""


def privileged_mutation_blocked() -> bool:
    """Block unless trusted observation explicitly reports active=False."""
    try:
        snapshot = observe()
        return not (isinstance(snapshot, dict)
                    and snapshot.get("active") is False)
    except Exception:
        return True


def require_privileged_mutation_admission() -> None:
    """Refuse a new helper invocation BEFORE request or game state mutation."""
    if privileged_mutation_blocked():
        raise PrivilegedMutationHold("agent_privileged_maintenance_hold_active")
