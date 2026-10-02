#!/usr/bin/env python3
"""Offline rehearsal for an atomic NeoForge + Server Pack transition.

This module is deliberately NOT wired to production Agents or HTTP endpoints.
Its adapter only works in a caller-provided test workspace. The rehearsal
requires an explicit, test-only adapter and checks recovery at each boundary.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RehearsalError(RuntimeError):
    def __init__(self, message: str, recovery: tuple[str, ...] = ()):
        super().__init__(message)
        self.recovery = recovery


def rehearse_staged_migration(
    *,
    revalidate: Callable[[], dict[str, Any]],
    capacity: Callable[[], dict[str, Any]],
    stage: Callable[[], Any],
    checkpoint: Callable[[], Any],
    activate: Callable[[], Any],
    doctor: Callable[[], bool],
    commit: Callable[[], Any],
    rollback: Callable[[], Any],
    cleanup: Callable[[], Any],
    test_only: bool = False,
) -> dict[str, Any]:
    """Model sequencing and compensation before building the real executor.

    The injected functions MUST be test fakes. This does not provide an
    instance lock, a real world hash comparison, or an actual backup verifier.
    """
    if test_only is not True:
        raise RehearsalError("offline rehearsal requires explicit test_only=True")
    plan = revalidate()
    if not isinstance(plan, dict) or plan.get("valid") is not True or plan.get("install_allowed") is not False:
        raise RehearsalError("migration preview must be current, verified and non-executable")
    space = capacity()
    if not isinstance(space, dict) or space.get("sufficient") is not True or space.get("install_allowed") is not False:
        raise RehearsalError("insufficient verified staging capacity")
    trace = ["revalidated", "capacity_checked"]
    checkpoint_ready = False
    staging_started = False
    primary_error: Exception | None = None
    try:
        # Staging must be isolated. Any callback failure must be compensated.
        staging_started = True
        stage()
        trace.append("staged")
        checkpoint()
        checkpoint_ready = True
        trace.append("checkpointed")
        activate()
        trace.append("activated")
        if doctor() is not True:
            raise RehearsalError("new loader or Server Pack failed readiness")
        trace.append("ready")
        commit()
        trace.append("committed")
        return {"status": "rehearsal_completed", "trace": trace, "production_enabled": False}
    except Exception as exc:
        primary_error = exc
        trace.append("failed")
        if checkpoint_ready:
            try:
                rollback()
                trace.append("rolled_back")
            except Exception as rollback_exc:
                trace.append("rollback_failed")
                raise RehearsalError(
                    "rehearsal failed and rollback also failed: manual intervention required",
                    tuple(trace),
                ) from rollback_exc
        else:
            trace.append("no_checkpoint_to_restore")
        raise RehearsalError("rehearsal stopped: " + str(primary_error), tuple(trace)) from primary_error
    finally:
        if staging_started:
            try:
                cleanup()
                trace.append("staging_cleaned")
            except Exception:
                # Keep the primary failure or recorded success semantics
                # truthful: cleanup failures MUST block acceptance.
                if primary_error is None:
                    raise RehearsalError("rehearsal completed but staging cleanup failed", tuple(trace))
