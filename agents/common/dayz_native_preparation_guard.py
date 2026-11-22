#!/usr/bin/env python3
"""Fail-closed gate for the startup-only DayZ shutdown message configuration."""
from __future__ import annotations
from typing import Any, Mapping

def require_stopped_instance(view: Mapping[str, Any] | None) -> None:
    """Require an Agent-local runtime observation, not a persisted desired state.

    This check must run under the per-instance lifecycle lock to prevent a
    concurrent DSM start from racing with the messages.xml materialization.
    """
    state = view.get("adapter_state") if isinstance(view, Mapping) else None
    if (
        not isinstance(state, Mapping)
        or state.get("available") is not True
        or str(state.get("active_state") or "").strip().lower() != "inactive"
        or str(view.get("observed_state") or "").strip().lower() != "stopped"
    ):
        raise RuntimeError(
            "DayZ native restart preparation requires a verified stopped instance; "
            "messages.xml is startup-only and no running-process countdown is guaranteed"
        )

__all__ = ["require_stopped_instance"]
