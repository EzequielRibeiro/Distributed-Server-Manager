#!/usr/bin/env python3
"""DSM #928: final Controller HTTP mutation admission gate, never an ACK.

This is the outermost installed handler wrapper.  Under an operator-owned
hold, new HTTP mutations fail closed before reaching child routing layers.
An opt-in shared flock also tracks whole requests across Controller processes;
it is NOT installed by the updater or enabled for live maintenance by itself.
"""
from __future__ import annotations

from functools import wraps
from pathlib import Path
import sys
from urllib.parse import urlparse

_AGENT_RUNTIME = Path(__file__).resolve().parents[1] / "agents/linux/runtime"
if str(_AGENT_RUNTIME) not in sys.path:
    sys.path.append(str(_AGENT_RUNTIME))

from game_uptime_maintenance_hold import observe as observe_no_drain_hold
from game_uptime_controller_agent_http_flock import (
    ControllerHttpLockUnavailable, shared_controller_agent_http_lock,
)

# Read-only authenticated observation must remain reachable during hold.
_READONLY_POST = frozenset({"/api/agent/no-drain/observe"})
_MUTATION_METHODS = ("do_POST", "do_PUT", "do_PATCH", "do_DELETE")


def _hold_blocks() -> bool:
    try:
        observed = observe_no_drain_hold()
        return not (isinstance(observed, dict) and observed.get("active") is False)
    except Exception:
        return True


def _deny(handler, *, locked: bool = False) -> None:
    handler.send_json(423, {
        "status": "blocked",
        "reason": ("controller_http_interprocess_fence_unavailable"
                   if locked else "controller_maintenance_hold_active"),
        "controller_http_acked": False,
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    })


def install_controller_mutation_gate(legacy) -> None:
    """Wrap existing handlers once, after ALL HTTP composition hooks are set."""
    handler = legacy.DashboardHandler
    if getattr(handler, "_dsm928_mutation_gate_installed", False):
        return

    for method_name in _MUTATION_METHODS:
        original = getattr(handler, method_name, None)
        if original is None:
            continue

        def wrap(target, verb):
            @wraps(target)
            def guarded(self, *args, **kwargs):
                path = urlparse(self.path).path
                if verb == "do_POST" and path in _READONLY_POST:
                    return target(self, *args, **kwargs)
                try:
                    with shared_controller_agent_http_lock():
                        if _hold_blocks():
                            return _deny(self)
                        return target(self, *args, **kwargs)
                except ControllerHttpLockUnavailable:
                    return _deny(self, locked=True)
            return guarded

        setattr(handler, method_name, wrap(original, method_name))

    handler._dsm928_mutation_gate_installed = True
