#!/usr/bin/env python3
"""Administrative service boundary for remote Agent decommissioning."""
from __future__ import annotations

from agent_admin_repository import AgentAdminRepository
from agent_uninstall_repository import AgentUninstallRepository
from registry_repository import RegistryRepository


def _node_role(backend, agent_id: str) -> str:
    repository = RegistryRepository(backend)
    repository.initialize()
    ph = repository.dialect.placeholder
    with repository.transaction() as session:
        row = session.execute(
            "SELECT n.role FROM agents a JOIN nodes n ON n.id=a.node_id "
            f"WHERE a.id={ph}",
            (agent_id,),
        ).fetchone()
    if row is None:
        raise LookupError("Agent not found")
    return str(row["role"] or "").strip().lower()


def _reject_hybrid_standalone_removal(backend, agent_id: str) -> None:
    if _node_role(backend, agent_id) == "hybrid":
        raise ValueError(
            "O Agent local do modo híbrido não usa a desinstalação/remocão de Agent standalone. "
            "Use Agents > Este Node > Desativar Agent local · manter Controller."
        )


def request_agent_uninstall(
    backend,
    *,
    agent_id: str,
    mode: str,
    confirmation: str,
    requested_by: str,
) -> dict:
    """Queue a typed remote uninstall while retaining Controller registration."""
    _reject_hybrid_standalone_removal(backend, agent_id)
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


def reconcile_completed_agent_uninstall(
    backend,
    *,
    agent_id: str,
    confirmation: str,
    reconciled_by: str,
) -> dict:
    """Reconcile a completed historical uninstall without deleting records."""
    if confirmation != agent_id:
        raise ValueError("confirmation must exactly match agent_id")

    _reject_hybrid_standalone_removal(backend, agent_id)
    AgentAdminRepository(backend).detail(agent_id)

    result = AgentUninstallRepository(
        backend
    ).reconcile_completed_decommission(agent_id)

    result["reconciled_by"] = str(reconciled_by or "system")
    result["remote_host_removal"] = False
    result["controller_only_lifecycle_reconciliation"] = True
    return result


def force_remove_controller_registration(
    backend,
    *,
    agent_id: str,
    confirmation: str,
    removed_by: str,
) -> dict:
    """Remove only Controller records; never imply host-side uninstall."""
    _reject_hybrid_standalone_removal(backend, agent_id)
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
    "reconcile_completed_agent_uninstall",
    "request_agent_uninstall",
]
