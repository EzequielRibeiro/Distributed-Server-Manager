#!/usr/bin/env python3
"""DSM #928: fail-closed admission for NEW privileged Agent mutations only.

This is not an in-flight fence, distributed ACK, transaction lease, or
authorization for update.sh --no-drain. It does not alter the hold reader.
"""
from __future__ import annotations

from game_uptime_maintenance_hold import observe
from functools import wraps

from game_uptime_privileged_flock import (
    PrivilegedHelperFenceUnavailable, shared_privileged_helper_lock,
)


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

def fence_privileged_helper_run(func):
    """Keep one opt-in shared kernel lock during the entire root helper run.

    This witnesses only the decorated parent process until its return. A
    separate child surviving parent exit is not fenced; never infer ACK.
    """
    @wraps(func)
    def guarded(*args, **kwargs):
        try:
            with shared_privileged_helper_lock():
                return func(*args, **kwargs)
        except PrivilegedHelperFenceUnavailable as exc:
            raise PrivilegedMutationHold(
                "agent_privileged_inflight_fence_unavailable") from exc
    return guarded
