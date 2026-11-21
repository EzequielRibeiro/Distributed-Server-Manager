#!/usr/bin/env python3
"""Controller receipt of remote #928 fence EVIDENCE, never quiescence ACK.

Called only AFTER AgentPairingRepository authenticates the credential.
The Controller also requires its own valid root-owned transaction marker,
with identical transaction/issuance/expiry. No durable replay cache, remote
operation fence, or transaction authority exists in this module.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping

_AGENT_RUNTIME = Path(__file__).resolve().parents[1] / "agents/linux/runtime"
if str(_AGENT_RUNTIME) not in sys.path:
    sys.path.append(str(_AGENT_RUNTIME))
from game_uptime_maintenance_hold import observe

CONTRACT = {"protocol": "dsm928-fence-evidence-readonly-v1", "schema": "1"}
_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_EVIDENCE_KEYS = {
    "kind", "schema_version", "agent_id", "request_id",
    "transaction_id", "issued_at", "expires_at", "observed_at",
    "contract", "agent_workers_fenced", "external_jobs_verified",
    "live_no_drain_authorized",
}


def receipt_for_authenticated_agent(
    evidence: Any, *, authenticated_agent_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Receive negative remote evidence on one authenticated heartbeat.

    This does NOT record, acknowledge, or authorize Agent quiescence.
    """
    if (not isinstance(authenticated_agent_id, str)
            or not _ID.fullmatch(authenticated_agent_id)):
        raise ValueError("invalid authenticated Agent identity")
    p = evidence if isinstance(evidence, Mapping) else {}
    when = int(time.time()) if now is None else now
    nonce = p.get("request_id")
    tx = p.get("transaction_id")
    issued, expires = p.get("issued_at"), p.get("expires_at")
    valid = (
        set(p) == _EVIDENCE_KEYS
        and p.get("kind") == "CapivaraNoDrainFenceEvidence"
        and type(p.get("schema_version")) is int and p["schema_version"] == 1
        and p.get("agent_id") == authenticated_agent_id
        and type(nonce) is str and bool(_NONCE.fullmatch(nonce))
        and type(tx) is str and bool(_NONCE.fullmatch(tx))
        and type(issued) is int and type(expires) is int
        and type(p.get("observed_at")) is int
        and not (p["observed_at"] > when + 30
                 or p["observed_at"] < when - 30)
        and 0 < issued <= when + 30
        and issued < expires <= issued + 900
        and issued <= when < expires
        and p.get("contract") == CONTRACT
        and p.get("agent_workers_fenced") is False
        and p.get("external_jobs_verified") is False
        and p.get("live_no_drain_authorized") is False
    )
    if valid:
        local = observe()
        valid = (
            local.get("active") is True
            and local.get("reason") == "root_owned_maintenance_hold"
            and local.get("transaction_id") == tx
            and type(local.get("issued_at")) is int
            and local["issued_at"] == issued
            and type(local.get("expires_at")) is int
            and local["expires_at"] == expires
        )
    return {
        "kind": "CapivaraNoDrainFenceEvidenceReceipt",
        "schema_version": 1,
        "agent_id": authenticated_agent_id,
        "request_id": nonce if type(nonce) is str
                      and _NONCE.fullmatch(nonce) else None,
        "transaction_id": tx if type(tx) is str
                          and _NONCE.fullmatch(tx) else None,
        "issued_at": issued if type(issued) is int else None,
        "expires_at": expires if type(expires) is int else None,
        "contract": dict(CONTRACT),
        "status": ("authenticated_evidence_received_unfenced"
                   if valid else "blocked"),
        "scope": "authenticated_heartbeat_wire_only",
        "agent_workers_fenced": False,
        "remote_agent_quiescence_acked": False,
        "live_no_drain_authorized": False,
    }
