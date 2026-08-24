#!/usr/bin/env python3
"""Project Agent-owned provisioning state into the legacy dashboard read model.

The distributed B10 pipeline is authoritative for execution.  The customer
Dashboard still reads ``runtime/resources`` and ``instances.status`` while that
legacy read model is being retired, so this module mirrors only status/progress
there.  It never installs content or materializes a runtime on the Controller.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from dashboard_repository import DashboardRepository

ROOT = Path(__file__).resolve().parents[1]
_AUTH_TOKENS = ("steam", "guard", "auth", "login", "credential", "licen")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _instance_location(backend, instance_id: str) -> tuple[str, str] | None:
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT node_id,game_id FROM instances WHERE id={ph}",
                (instance_id,),
            ).fetchone()
        finally:
            session.close()
    if row is None:
        return None
    return str(row["node_id"] or ""), str(row["game_id"] or "")


def dashboard_provision_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Translate persistent B10 state to the current customer Dashboard contract."""
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
    auth_failure = bool(error) and any(token in error.lower() for token in _AUTH_TOKENS)

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
    elif distributed_status == "failed" and auth_failure:
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
    root: Path = ROOT,
) -> dict[str, Any]:
    """Persist a read-only control-plane projection of an Agent B10 operation."""
    source = state if isinstance(state, dict) else {}
    instance_id = str(source.get("instance_id") or "").strip()
    if not instance_id:
        raise ValueError("instance_id is required for provisioning projection")
    location = _instance_location(backend, instance_id)
    if location is None:
        raise ValueError("instance not found for provisioning projection")
    node_id, game_id = location
    payload = dashboard_provision_state(source)
    resource = Path(root) / "runtime" / "resources" / node_id / game_id / instance_id
    _write_json(resource / "provision.json", payload)
    health = (
        "pending"
        if payload["status"] in {"queued", "provisioning", "pending_steam_auth"}
        else ("healthy" if payload["status"] in {"offline", "running"} else "error")
    )
    _write_json(
        resource / "server.json",
        {"status": {"state": payload["status"], "health": health}},
    )
    DashboardRepository(backend).update_instance_status(instance_id, payload["status"])
    return payload


__all__ = ["dashboard_provision_state", "project_agent_provisioning"]
