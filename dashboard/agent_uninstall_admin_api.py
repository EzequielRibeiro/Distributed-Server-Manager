#!/usr/bin/env python3
"""Administrative service boundary for remote Agent decommissioning."""
from __future__ import annotations

from agent_admin_repository import AgentAdminRepository
from agent_uninstall_repository import AgentUninstallRepository


def request_agent_uninstall(
    backend,
    *,
    agent_id: str,
    mode: str,
    confirmation: str,
    requested_by: str,
) -> dict:
    """Queue a typed remote uninstall while retaining Controller registration."""
    detail = AgentAdminRepository(backend).detail(agent_id)
    state = AgentUninstallRepository(backend).request(
        agent_id,
        mode=mode,
        requested_by=requested_by,
        confirmation=confirmation,
    )
    return {
        "agent_id": agent_id,
        "node_id": detail.get("node_id"),
        "remote_host_removal": True,
        "controller_registration_retained": True,
        "uninstall": state,
    }


def agent_uninstall_state(backend, *, agent_id: str) -> dict | None:
    """Return the current decommissioning state without mutating it."""
    AgentAdminRepository(backend).detail(agent_id)
    return AgentUninstallRepository(backend).state(agent_id)


def force_remove_controller_registration(
    backend,
    *,
    agent_id: str,
    confirmation: str,
    removed_by: str,
) -> dict:
    """Remove only Controller records; never imply host-side uninstall."""
    result = AgentAdminRepository(backend).remove(
        agent_id,
        confirmation=confirmation,
        actor=removed_by,
    )
    result["remote_host_removal"] = False
    result["controller_only"] = True
    result["warning"] = "A máquina remota e seus arquivos não foram desinstalados por esta operação."
    return result


__all__ = [
    "agent_uninstall_state",
    "force_remove_controller_registration",
    "request_agent_uninstall",
]
