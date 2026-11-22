"""#928 admission gate for detached Server Pack finalization workers.

A root-owned maintenance hold blocks new launches and child mutations.
This is an admission-only safety check, NOT an in-flight/distributed ACK.
"""
from __future__ import annotations

from game_uptime_maintenance_hold import observe


class FinalizationMaintenanceHold(RuntimeError):
    """A maintenance hold or untrusted evidence forbids finalization."""


def require_finalization_admission() -> None:
    """Fail closed on invalid, expired, pending or unreadable root evidence."""
    try:
        state = observe()
    except Exception as exc:
        raise FinalizationMaintenanceHold(
            "serverpack_finalization_maintenance_evidence_unavailable"
        ) from exc
    if not isinstance(state, dict) or state.get("active") is not False:
        raise FinalizationMaintenanceHold(
            "serverpack_finalization_maintenance_hold_active"
        )
