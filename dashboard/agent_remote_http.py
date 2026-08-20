#!/usr/bin/env python3
"""HTTP-safe service contract for remote Agent enrollment and heartbeat."""

from __future__ import annotations

from typing import Any

from agent_heartbeat_api import record_agent_heartbeat
from agent_installation_api import bind_installation_after_enrollment
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
        # Pairing is a security boundary. A dashboard metadata failure must not
        # invalidate a permanent identity already issued or invite token replay.
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


def dispatch_heartbeat(payload: dict[str, Any] | None, *, headers, backend) -> tuple[int, dict[str, Any]]:
    credential_id = str(headers.get("X-Capivara-Agent-Credential", "")).strip()
    credential_secret = str(headers.get("X-Capivara-Agent-Secret", "")).strip()
    fingerprint = str(headers.get("X-Capivara-Agent-Fingerprint", "")).strip() or None
    try:
        identity = AgentPairingRepository(backend).authenticate(
            credential_id=credential_id,
            credential_secret=credential_secret,
            fingerprint=fingerprint,
        )
        result = record_agent_heartbeat(identity["agent_id"], payload, backend=backend)
        status = str(identity.get("status", "")).strip().lower()
        if status == "pairing":
            status = AgentLifecycleRepository(backend).transition(identity["agent_id"], "active").target
        result["status"] = status
    except AgentCredentialInvalid:
        return 401, {"error": "agent_authentication_failed", "message": "Identidade do Agent inválida."}
    except Exception:
        return 500, {"error": "heartbeat_failed", "message": "Não foi possível registrar o heartbeat."}
    return 200, result
