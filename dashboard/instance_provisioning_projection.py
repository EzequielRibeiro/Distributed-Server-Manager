#!/usr/bin/env python3
"""Expose Agent-owned provisioning state through the database-backed Dashboard contract."""
from __future__ import annotations

import time
from typing import Any

from dashboard_repository import DashboardRepository


def dashboard_provision_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Translate persistent provisioning state to the customer Dashboard contract."""
    source = state if isinstance(state, dict) else {}
    distributed_status = str(source.get("status") or "queued").strip().lower()
    step = str(source.get("current_step") or distributed_status or "queued").strip()
    try:
        progress = int(source.get("progress", 0) or 0)
    except (TypeError, ValueError):
        progress = 0
    progress = max(0, min(progress, 100))
    result = source.get("result") if isinstance(source.get("result"), dict) else {}
    error = str(source.get("last_error") or result.get("error") or "").strip()
    steam_auth_required = bool(result.get("steam_auth_required"))

    if distributed_status in {"queued", "delivered"}:
        status = "queued"
        stage = "queued"
        progress = max(5, min(progress, 15))
        message = "Instalação aguardando o Agent…"
    elif distributed_status == "running":
        status = "provisioning"
        stage = step or "provisioning"
        progress = max(5, min(progress, 99))
        messages = {
            "accepted": "O Agent aceitou o provisionamento…",
            "prepare_workspace": "Preparando o espaço da instância no Agent…",
            "validate_ports": "Validando as portas reservadas no Agent…",
            "install_content": "Verificando e instalando o game-data no Agent…",
            "build_runtime_spec": "Preparando a configuração de runtime…",
            "materialize_runtime": "Materializando a instância no Agent…",
            "initial_reconcile": "Validando o runtime materializado no Agent…",
        }
        message = messages.get(stage, "Provisionamento em execução no Agent…")
    elif distributed_status == "completed":
        observed = str(result.get("observed_state") or "stopped").strip().lower()
        status = "running" if observed == "running" else "offline"
        stage = "completed"
        progress = 100
        message = "Instalação concluída. O servidor está pronto para iniciar."
    elif distributed_status == "failed" and steam_auth_required:
        status = "pending_steam_auth"
        stage = "steam_auth"
        progress = 35
        message = "A instalação está aguardando autenticação Steam pelo administrador."
    else:
        status = "failed"
        stage = step or "failed"
        progress = max(progress, 35)
        message = "Não foi possível concluir o provisionamento no Agent."

    payload: dict[str, Any] = {
        "status": status,
        "stage": stage,
        "progress": progress,
        "message": message,
        "updated_at": int(time.time()),
        "distributed": True,
    }
    if source.get("provisioning_id"):
        payload["provisioning_id"] = str(source["provisioning_id"])
    if error:
        payload["error"] = error
    return payload


def project_agent_provisioning(
    backend,
    state: dict[str, Any] | None,
    *,
    root=None,
) -> dict[str, Any]:
    """Synchronize the public instance status without creating filesystem state."""
    source = state if isinstance(state, dict) else {}
    instance_id = str(source.get("instance_id") or "").strip()
    if not instance_id:
        raise ValueError("instance_id is required for provisioning state")
    payload = dashboard_provision_state(source)
    DashboardRepository(backend).update_instance_status(instance_id, payload["status"])
    return payload


__all__ = ["dashboard_provision_state", "project_agent_provisioning"]
