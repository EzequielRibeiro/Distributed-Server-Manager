#!/usr/bin/env python3
"""HTTP-safe service contract for remote Agent enrollment and heartbeat."""

from __future__ import annotations

from typing import Any

from agent_game_data_repository import AgentGameDataRepository
from agent_heartbeat_api import record_agent_heartbeat
from agent_installation_api import bind_installation_after_enrollment
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_lifecycle_repository import AgentLifecycleRepository
from agent_pairing_api import enroll_remote_agent
from agent_pairing_repository import (
    AgentCredentialInvalid,
    AgentPairingRepository,
    PairingRegistrationConflict,
    PairingTokenConsumed,
    PairingTokenExpired,
    PairingTokenInvalid,
)
from agent_update_repository import AgentUpdateRepository

ENROLL_PATH = "/api/agent/enroll"
HEARTBEAT_PATH = "/api/agent/heartbeat"


def dispatch_enroll(payload: dict[str, Any] | None, *, backend) -> tuple[int, dict[str, Any]]:
    try:
        result = enroll_remote_agent(backend, payload)
    except (PairingTokenInvalid, PairingTokenExpired, PairingTokenConsumed):
        return 401, {"error": "pairing_rejected", "message": "Pareamento inválido ou expirado."}
    except (PairingRegistrationConflict, ValueError):
        return 409, {"error": "pairing_conflict", "message": "Não foi possível registrar este Agent."}
    except Exception:
        return 500, {"error": "pairing_failed", "message": "Não foi possível concluir o pareamento."}

    tracking_bound = True
    try:
        bind_installation_after_enrollment(
            backend,
            pairing_token=str((payload or {}).get("pairing_token", "")),
            agent_id=str(result["agent_id"]),
        )
    except Exception:
        tracking_bound = False

    identity = dict(result.get("identity") or {})
    return 201, {
        "agent_id": result["agent_id"],
        "node_id": result["node_id"],
        "controller_id": result["controller_id"],
        "status": result["status"],
        "credential_id": identity["credential_id"],
        "credential_secret": identity["credential_secret"],
        "credential_type": identity["credential_type"],
        "fingerprint": identity["fingerprint"],
        "pairing_token_consumed": bool(result.get("pairing_token_consumed")),
        "installation_tracking_bound": tracking_bound,
    }


def _attach_update_state(result: dict[str, Any], body: dict[str, Any], *, agent_id: str, backend) -> None:
    """Best-effort update coordination that must never suppress Agent health."""
    try:
        updates = AgentUpdateRepository(backend)
        updates.initialize()
        update_state = updates.reconcile_after_heartbeat(
            agent_id,
            body.get("capivara_version"),
            result.get("health_status", "online"),
        )
        update_result = body.get("update_result") if isinstance(body.get("update_result"), dict) else None
        if update_result and str(update_result.get("status", "")).lower() == "failed":
            update_state = updates.mark_failed(
                agent_id,
                str(update_result.get("error", "update failed"))[:2000],
            )
            command = None
        else:
            command = updates.command_for_agent(agent_id)
            if command and update_state.get("update_status") == "planned":
                update_state = updates.mark_updating(agent_id)
            if command:
                result["update"] = command
        result["update_state"] = update_state
    except Exception:
        result["update_state"] = {"update_status": "unavailable"}


def _attach_game_data_state(result: dict[str, Any], body: dict[str, Any], *, agent_id: str, backend) -> None:
    """Best-effort game-data coordination without coupling liveness to job state."""
    try:
        jobs = AgentGameDataRepository(backend)
        jobs.initialize()
        reported = body.get("game_data_result") if isinstance(body.get("game_data_result"), dict) else None
        reported_state = jobs.apply_result(agent_id, reported) if reported else None
        command = jobs.command_for_agent(agent_id)
        command_state = None
        if command:
            command_state = jobs.mark_delivered(str(command["job_id"]))
            result["game_data_command"] = command
        result["game_data_state"] = reported_state or command_state or {"status": "idle"}
    except Exception:
        result["game_data_state"] = {"status": "unavailable"}


def _attach_instance_state(result: dict[str, Any], body: dict[str, Any], *, agent_id: str, backend) -> None:
    """Best-effort, game-agnostic instance observation command transport."""
    try:
        commands = AgentInstanceRuntimeRepository(backend)
        commands.initialize()
        reported = body.get("instance_result") if isinstance(body.get("instance_result"), dict) else None
        reported_state = commands.apply_result(agent_id, reported) if reported else None
        command = commands.command_for_agent(agent_id)
        command_state = None
        if command:
            command_state = commands.mark_delivered(str(command["command_id"]))
            result["instance_command"] = command
        result["instance_state"] = reported_state or command_state or {"status": "idle"}
    except Exception:
        result["instance_state"] = {"status": "unavailable"}


def dispatch_heartbeat(payload: dict[str, Any] | None, *, headers, backend) -> tuple[int, dict[str, Any]]:
    credential_id = str(headers.get("X-Capivara-Agent-Credential", "")).strip()
    credential_secret = str(headers.get("X-Capivara-Agent-Secret", "")).strip()
    fingerprint = str(headers.get("X-Capivara-Agent-Fingerprint", "")).strip() or None
    body = payload if isinstance(payload, dict) else {}
    try:
        identity = AgentPairingRepository(backend).authenticate(
            credential_id=credential_id,
            credential_secret=credential_secret,
            fingerprint=fingerprint,
        )
        result = record_agent_heartbeat(identity["agent_id"], body, backend=backend)
        status = str(identity.get("status", "")).strip().lower()
        if status == "pairing":
            status = AgentLifecycleRepository(backend).transition(identity["agent_id"], "active").target
        result["status"] = status
        _attach_update_state(result, body, agent_id=identity["agent_id"], backend=backend)
        _attach_game_data_state(result, body, agent_id=identity["agent_id"], backend=backend)
        _attach_instance_state(result, body, agent_id=identity["agent_id"], backend=backend)
    except AgentCredentialInvalid:
        return 401, {"error": "agent_authentication_failed", "message": "Identidade do Agent inválida."}
    except Exception:
        return 500, {"error": "heartbeat_failed", "message": "Não foi possível registrar o heartbeat."}
    return 200, result
