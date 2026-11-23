#!/usr/bin/env python3
"""DSM #928 phase-2: unprivileged, read-only remote fence EVIDENCE envelope.

This is not a quiescence ACK. A valid local root-owned hold permits an
Agent to report a transaction-correlated *negative* readiness observation.
The Controller must authenticate the Agent and correlate its own hold.
No file writes, background changes, or update authorization are possible.
"""
from __future__ import annotations

import re
import secrets
import time
from typing import Any, Mapping

from game_uptime_maintenance_hold import observe
from game_uptime_transaction_binding import (
    ReleaseBindingBlocked, binding_for_hold,
)

CONTRACT = {"protocol": "dsm928-fence-evidence-readonly-v1", "schema": "1"}
CONTRACT_V2 = {"protocol": "dsm928-fence-evidence-release-bound-readonly-v2", "schema": "2"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")


def _hold_identity(hold: Any, now: int) -> tuple[str, int, int] | None:
    if not isinstance(hold, Mapping):
        return None
    tx = hold.get("transaction_id")
    issued, expires = hold.get("issued_at"), hold.get("expires_at")
    if (hold.get("active") is not True
            or hold.get("reason") != "root_owned_maintenance_hold"
            or type(tx) is not str or not _NONCE.fullmatch(tx)
            or type(issued) is not int or type(expires) is not int
            or not (0 < issued <= now + 30)
            or not (issued < expires <= issued + 900)
            or not (issued <= now < expires)):
        return None
    return tx, issued, expires


def build_fence_evidence(agent_id: str, *,
                         now: int | None = None) -> dict[str, Any] | None:
    """Only send if a trusted local transaction marker currently exists."""
    if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
        raise ValueError("invalid Agent identity")
    when = int(time.time()) if now is None else now
    observed = observe()
    hold = _hold_identity(observed, when)
    if hold is None:
        return None
    try:
        release_binding = binding_for_hold(observed, now=when)
    except ReleaseBindingBlocked:
        # Corrupt, mismatched or expired privileged evidence cannot be
        # downgraded to a legacy transaction-only report.
        return None
    tx, issued, expires = hold
    evidence = {
        "kind": "CapivaraNoDrainFenceEvidence",
        "schema_version": 1,
        "agent_id": agent_id,
        "request_id": secrets.token_hex(16),
        "transaction_id": tx,
        "issued_at": issued,
        "expires_at": expires,
        "observed_at": when,
        "contract": dict(CONTRACT),
        "agent_workers_fenced": False,
        "external_jobs_verified": False,
        "live_no_drain_authorized": False,
    }
    if release_binding is not None:
        evidence["contract"] = dict(CONTRACT_V2)
        evidence["release_sha256"] = release_binding["release_sha256"]
    return evidence


def verify_fence_receipt(evidence: Any, receipt: Any, *,
                         now: int | None = None) -> dict[str, Any]:
    """Fail closed on missing/forged/stale/cross-transaction Controller reply.

    The maximum successful result is a *wire receipt*, never remote readiness.
    """
    when = int(time.time()) if now is None else now
    p = evidence if isinstance(evidence, Mapping) else {}
    r = receipt if isinstance(receipt, Mapping) else {}
    keys = {
        "kind", "schema_version", "agent_id", "request_id",
        "transaction_id", "issued_at", "expires_at", "observed_at",
        "contract", "agent_workers_fenced", "external_jobs_verified",
        "live_no_drain_authorized",
    }
    version_two = p.get("contract") == CONTRACT_V2
    if version_two:
        keys = keys | {"release_sha256"}
    expected_contract = CONTRACT_V2 if version_two else CONTRACT
    valid_evidence = (
        set(p) == keys
        and p.get("kind") == "CapivaraNoDrainFenceEvidence"
        and type(p.get("schema_version")) is int and p["schema_version"] == 1
        and isinstance(p.get("agent_id"), str)
        and bool(_ID.fullmatch(p["agent_id"]))
        and isinstance(p.get("request_id"), str)
        and bool(_NONCE.fullmatch(p["request_id"]))
        and p.get("contract") == expected_contract
        and (not version_two or
             type(p.get("release_sha256")) is str and
             bool(re.fullmatch(r"[0-9a-f]{64}", p["release_sha256"])))
        and p.get("agent_workers_fenced") is False
        and p.get("external_jobs_verified") is False
        and p.get("live_no_drain_authorized") is False
        and type(p.get("observed_at")) is int
        and abs(when - p["observed_at"]) <= 30
        and _hold_identity({
            "active": True, "reason": "root_owned_maintenance_hold",
            "transaction_id": p.get("transaction_id"),
            "issued_at": p.get("issued_at"),
            "expires_at": p.get("expires_at"),
        }, when) is not None
    )
    receipt_keys = {
        "kind", "schema_version", "agent_id", "request_id",
        "transaction_id", "issued_at", "expires_at", "contract",
        "status", "scope", "agent_workers_fenced",
        "remote_agent_quiescence_acked", "live_no_drain_authorized",
    }
    if version_two:
        receipt_keys = receipt_keys | {"release_sha256"}
    valid_receipt = (
        valid_evidence and set(r) == receipt_keys
        and r.get("kind") == "CapivaraNoDrainFenceEvidenceReceipt"
        and type(r.get("schema_version")) is int and r["schema_version"] == 1
        and all(r.get(k) == p[k] for k in (
            "agent_id", "request_id", "transaction_id", "issued_at",
            "expires_at",
        ))
        and r.get("contract") == expected_contract
        and (not version_two or
             r.get("release_sha256") == p.get("release_sha256"))
        and r.get("status") == "authenticated_evidence_received_unfenced"
        and r.get("scope") == "authenticated_heartbeat_wire_only"
        and r.get("agent_workers_fenced") is False
        and r.get("remote_agent_quiescence_acked") is False
        and r.get("live_no_drain_authorized") is False
    )
    return {
        "status": ("receipt_verified_not_quiesced"
                   if valid_receipt else "receipt_unverified"),
        "wire_receipt_verified": bool(valid_receipt),
        "remote_agent_quiescence_acked": False,
        "live_no_drain_authorized": False,
    }
