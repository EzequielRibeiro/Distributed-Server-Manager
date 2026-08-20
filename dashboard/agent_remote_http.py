#!/usr/bin/env python3
"""HTTP-safe service contract for remote Agent enrollment and heartbeat."""

from __future__ import annotations

from typing import Any

from agent_authenticated_api import authenticated_agent_heartbeat
from agent_lifecycle_repository import AgentLifecycleRepository
from agent_pairing_api import enroll_agent
from agent_pairing_repository import (
    AgentCredentialInvalid,
    PairingRegistrationConflict,
    PairingTokenConsumed,
    PairingTokenExpired,
    PairingTokenInvalid,
)

ENROLL_PATH = "/api/agent/enroll"
HEARTBEAT_PATH = "/api/agent/heartbeat"


def dispatch_enroll(payload: dict[str, Any] | None, *, backend) -> tuple[int, dict[str, Any]]:
    try:
        result = enroll_agent(backend, payload)
    except (PairingTokenInvalid, PairingTokenExpired, PairingTokenConsumed):
        return 401, {"error": "pairing_rejected", "message": "Pareamento inválido ou expirado."}
    except (PairingRegistrationConflict, ValueError):
        return 409, {"error": "pairing_conflict", "message": "Não foi possível registrar este Agent."}
    except Exception:
        return 500, {"error": "pairing_failed", "message": "Não foi possível concluir o pareamento."}
    return 201, result


def dispatch_heartbeat(
    payload: dict[str, Any] | None,
    *,
    headers,
    backend,
) -> tuple[int, dict[str, Any]]:
    credential_id = str(headers.get("X-Capivara-Agent-Credential", "")).strip()
    credential_secret = str(headers.get("X-Capivara-Agent-Secret", "")).strip()
    fingerprint = str(headers.get("X-Capivara-Agent-Fingerprint", "")).strip() or None
    try:
        result = authenticated_agent_heartbeat(
            backend,
            credential_id=credential_id,
            credential_secret=credential_secret,
            fingerprint=fingerprint,
            payload=payload,
        )
        # A Controller-issued one-time token is explicit trust for bootstrap.
        # The first authenticated heartbeat proves possession of the permanent
        # credential and completes pairing -> active atomically through lifecycle.
        if str(result.get("status", "")).strip().lower() == "pairing":
            transition = AgentLifecycleRepository(backend).transition(result["agent_id"], "active")
            result["status"] = transition.target
    except AgentCredentialInvalid:
        return 401, {"error": "agent_authentication_failed", "message": "Identidade do Agent inválida."}
    except Exception:
        return 500, {"error": "heartbeat_failed", "message": "Não foi possível registrar o heartbeat."}
    return 200, result
