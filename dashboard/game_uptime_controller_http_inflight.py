#!/usr/bin/env python3
"""DSM #928: process-local accounting for in-flight Controller Agent mutations.

This is deliberately NOT a quiescence ACK, cross-process lock, update gate or
persistent journal. A zero count only means the three covered dispatchers are
not currently executing *in this Python process*. A future coordinator must
fence every process/HTTP route and external job before considering an update.
"""
from __future__ import annotations

from functools import wraps
import os
from threading import Lock
from typing import Any, Callable

_OPERATIONS = ("enroll", "heartbeat", "uninstall_result")
_LOCK = Lock()
_ACTIVE = {name: 0 for name in _OPERATIONS}
_GENERATION = 0


def track_controller_agent_mutation(operation: str) -> Callable:
    """Count the *entire* dispatcher invocation, including failure paths."""
    if operation not in _ACTIVE:
        raise ValueError("unknown_controller_agent_mutation")

    def decorate(dispatch: Callable) -> Callable:
        @wraps(dispatch)
        def tracked(*args: Any, **kwargs: Any) -> Any:
            global _GENERATION
            with _LOCK:
                _ACTIVE[operation] += 1
                _GENERATION += 1
            try:
                return dispatch(*args, **kwargs)
            finally:
                with _LOCK:
                    _ACTIVE[operation] -= 1
                    _GENERATION += 1
        return tracked
    return decorate


def observe_controller_agent_inflight() -> dict[str, Any]:
    """Read-only lower-bound inventory, never a positive fence result.

    Never infer distributed quiescence from a zero count. The identity is
    process-local, resets on restart and cannot see other dashboard PIDs.
    """
    with _LOCK:
        active = dict(_ACTIVE)
        generation = _GENERATION
    return {
        "status": "process_local_observation_only",
        "scope": "three_agent_http_dispatchers_in_this_pid_only",
        "pid": os.getpid(),
        "generation": generation,
        "inflight": active,
        "inflight_total": sum(active.values()),
        "controller_http_acked": False,
        "remote_agents_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
