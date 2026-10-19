#!/usr/bin/env python3
"""Controlled stop state machine for customer-confirmed Server Pack migration.

This helper has no implicit side effects: the caller supplies an instance adapter.
It does not authorize migration or publish content. Call only after the Controller
request has passed the explicit customer confirmation and Agent policy gates.
"""
from __future__ import annotations

import time
from typing import Any


class ControlledStopError(RuntimeError):
    pass


_STOPPED = frozenset({"inactive"})
_RUNNING = frozenset({"active", "activating", "deactivating"})


def ensure_stopped(record: dict[str, Any], adapter: Any, *,
                   timeout_seconds: float = 60.0,
                   poll_seconds: float = 1.0,
                   monotonic=time.monotonic,
                   sleep=time.sleep) -> dict[str, Any]:
    """Request stop once if running; require confirmed inactive before return.

    Never treat 'deactivating' as stopped. A failed/unknown state fails closed.
    A caller must handle restoring the previous running state after failure.
    """
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("stop timeout and polling interval must be positive")
    initial = str(adapter.status(record).get("active_state") or "").lower()
    if initial in _STOPPED:
        return {"previous_state": initial, "stop_requested": False}
    if initial not in _RUNNING:
        raise ControlledStopError(f"cannot stop instance from state: {initial or 'unknown'}")
    if initial in {"active", "activating"}:
        adapter.stop(record)
    deadline = monotonic() + timeout_seconds
    while True:
        state = str(adapter.status(record).get("active_state") or "").lower()
        if state in _STOPPED:
            return {"previous_state": initial, "stop_requested": initial != "deactivating"}
        if state not in _RUNNING:
            raise ControlledStopError(f"instance entered unsafe state during stop: {state or 'unknown'}")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ControlledStopError("instance stop confirmation timed out")
        sleep(min(poll_seconds, remaining))
