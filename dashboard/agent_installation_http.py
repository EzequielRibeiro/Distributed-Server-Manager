#!/usr/bin/env python3
"""Transport-neutral HTTP dispatchers for Agent installation UI."""
from __future__ import annotations
from pathlib import Path
import sys
from typing import Any

_AGENT_RUNTIME = Path(__file__).resolve().parents[1] / "agents/linux/runtime"
if str(_AGENT_RUNTIME) not in sys.path:
    sys.path.append(str(_AGENT_RUNTIME))

from game_uptime_maintenance_hold import observe as observe_no_drain_hold
from game_uptime_controller_agent_http_flock import (
    ControllerHttpLockUnavailable, shared_controller_agent_http_lock,
)
from agent_connection_api import test_agent_connection_for_user
from agent_installation_api import agent_installation_status_for_user, create_agent_installation_for_user
from agent_release_service import AgentReleaseError, list_agent_releases

AGENT_INSTALLATIONS_PATH = "/api/agents/installations"
AGENT_INSTALLATION_TEST_PATH = "/api/agents/installations/test-connection"
AGENT_INSTALLATION_STATUS_PATH = "/api/agents/installations/status"
AGENT_RELEASES_PATH = "/api/agents/releases"

def _error(exc: Exception) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, PermissionError): return 403,{"error":str(exc)}
    if isinstance(exc, NotImplementedError): return 501,{"error":str(exc)}
    if isinstance(exc, AgentReleaseError): return 502,{"error":str(exc)}
    if isinstance(exc,(ValueError,LookupError)): return 400,{"error":str(exc)}
    return 500,{"error":"failed to manage Agent installation"}

def _maintenance_blocked() -> bool:
    """Only an explicit, valid inactive hold admits an Agent installation."""
    try:
        evidence = observe_no_drain_hold()
        return not (isinstance(evidence, dict) and evidence.get("active") is False)
    except Exception:
        return True


def _maintenance_denial(reason: str) -> tuple[int, dict[str, Any]]:
    return 423, {
        "status": "blocked",
        "reason": reason,
        "controller_http_acked": False,
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }


def dispatch_agent_installation_post(path: str, payload, *, user, backend):
    """Fence remote installation and connection probes for their entire call.

    The shared inode is the same opt-in Controller Agent HTTP witness used by
    enroll/heartbeat/uninstall and Console Push.  With the opt-in disabled,
    the root-owned hold still blocks remote operations, fail-closed.
    """
    if path not in {AGENT_INSTALLATIONS_PATH, AGENT_INSTALLATION_TEST_PATH}:
        return None
    try:
        with shared_controller_agent_http_lock():
            if _maintenance_blocked():
                return _maintenance_denial("controller_maintenance_hold_active")
            try:
                if path == AGENT_INSTALLATION_TEST_PATH:
                    return 200, test_agent_connection_for_user(user, payload)
                return 201, create_agent_installation_for_user(
                    user, backend, payload)
            except Exception as exc:
                return _error(exc)
    except ControllerHttpLockUnavailable:
        return _maintenance_denial("controller_http_interprocess_fence_unavailable")

def dispatch_agent_installation_get(path: str,*,user,backend,installation_id: str|None=None,platform: str|None=None,include_prereleases: bool=False):
    try:
        role=str((user or {}).get("role","")).strip().lower()
        if role not in {"admin","controller"}: raise PermissionError("Agent installation is not permitted")
        if path==AGENT_RELEASES_PATH:
            selected_platform=str(platform or "linux").strip().lower()
            releases=list_agent_releases(selected_platform,include_prereleases=bool(include_prereleases))
            return 200,{"platform":selected_platform,"releases":releases,"recommended":releases[0]["tag"] if releases else None}
        if path!=AGENT_INSTALLATION_STATUS_PATH: return None
        return 200,agent_installation_status_for_user(user,backend,str(installation_id or ""))
    except Exception as exc: return _error(exc)
