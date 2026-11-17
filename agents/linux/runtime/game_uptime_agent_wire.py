#!/usr/bin/env python3
"""Opt-in, non-mutating Agent half of the DSM #928 heartbeat diagnostic.

A successful wire exchange is NOT systemd, schema, process, rollback or
production no-drain proof. Older Controllers safely ignore optional probes.
"""
from __future__ import annotations
import re
import secrets
from typing import Any, Mapping

WIRE_CONTRACT = {
    "protocol": "dsm928-readonly-v1",
    "schema": "1",
    "controller_api": "agent-heartbeat-v1",
    "agent_api": "agent-heartbeat-v1",
}
_ID = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")


def build_probe(agent_id: str) -> dict[str, Any]:
    if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
        raise ValueError("invalid agent id")
    return {
        "kind": "CapivaraNoDrainCompatibilityProbe",
        "schema_version": 1,
        "agent_id": agent_id,
        "request_id": secrets.token_hex(16),
        "contract": dict(WIRE_CONTRACT),
        "live_no_drain_authorized": False,
    }


def verify_offer(probe: Mapping[str, Any], offer: Any) -> dict[str, Any]:
    """Fail closed for absent, malformed, substituted or mismatched response.

    Do not use returned value as permission for update or service operations.
    """
    offered = offer if isinstance(offer, Mapping) else {}
    valid_probe = (
        isinstance(probe, Mapping)
        and probe.get("kind") == "CapivaraNoDrainCompatibilityProbe"
        and isinstance(probe.get("agent_id"), str)
        and isinstance(probe.get("request_id"), str)
        and bool(_NONCE.fullmatch(probe["request_id"]))
        and probe.get("contract") == WIRE_CONTRACT
        and probe.get("live_no_drain_authorized") is False
    )
    valid = (
        valid_probe
        and offered.get("kind") == "CapivaraNoDrainCompatibilityOffer"
        and type(offered.get("schema_version")) is int
        and offered["schema_version"] == 1
        and offered.get("agent_id") == probe["agent_id"]
        and offered.get("request_id") == probe["request_id"]
        and offered.get("contract") == WIRE_CONTRACT
        and offered.get("status") == "wire_compatible"
        and offered.get("scope") == "authenticated_heartbeat_read_only"
        and offered.get("live_no_drain_authorized") is False
    )
    return {
        "kind": "CapivaraNoDrainWireDiagnostic",
        "wire_compatible": bool(valid),
        "reason": "authenticated_envelope_matched" if valid else "missing_or_invalid_offer",
        "live_no_drain_authorized": False,
    }
