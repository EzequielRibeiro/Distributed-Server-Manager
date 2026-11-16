#!/usr/bin/env python3
"""Read-only versioned #928 compatibility exchange over authenticated heartbeat.

Compatibility here covers only the diagnostic message envelope; it is NOT a
claim that binaries, schema migrations, systemd or games survive an upgrade.
This module never mutates Controller state or issues update instructions.
"""
from __future__ import annotations
import re
from typing import Any, Mapping

WIRE_CONTRACT = {
    "protocol": "dsm928-readonly-v1",
    "schema": "1",
    "controller_api": "agent-heartbeat-v1",
    "agent_api": "agent-heartbeat-v1",
}
_ID = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")


def assess_authenticated_probe(probe: Any, *, authenticated_agent_id: str) -> dict[str, Any]:
    """Reply only to credentials already validated by AgentPairingRepository.

    Caller must pass the authenticated identity, not a value from body.agent_id.
    All malformed or stale probes are blocked, never converted into commands.
    """
    agent_id = authenticated_agent_id if isinstance(authenticated_agent_id, str) else ""
    if not _ID.fullmatch(agent_id):
        raise ValueError("invalid authenticated agent identity")
    req = probe if isinstance(probe, Mapping) else {}
    nonce = req.get("request_id")
    nonce_valid = isinstance(nonce, str) and bool(_NONCE.fullmatch(nonce))
    identity_matches = req.get("agent_id") == agent_id
    contract = req.get("contract")
    contract_matches = (
        isinstance(contract, Mapping)
        and set(contract) == set(WIRE_CONTRACT)
        and all(type(contract[k]) is str and contract[k] == v
                for k, v in WIRE_CONTRACT.items())
    )
    valid = (req.get("kind") == "CapivaraNoDrainCompatibilityProbe"
             and type(req.get("schema_version")) is int
             and req["schema_version"] == 1
             and req.get("live_no_drain_authorized") is False
             and nonce_valid and identity_matches and contract_matches)
    return {
        "kind": "CapivaraNoDrainCompatibilityOffer",
        "schema_version": 1,
        "agent_id": agent_id,
        "request_id": nonce if nonce_valid else None,
        "contract": dict(WIRE_CONTRACT),
        "status": "wire_compatible" if valid else "blocked",
        "reason": "diagnostic_envelope_match" if valid else "contract_or_identity_mismatch",
        "scope": "authenticated_heartbeat_read_only",
        "live_no_drain_authorized": False,
    }
