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



def correlate_authenticated_fence_receipts(
    expected_agent_ids: list[str] | tuple[str, ...],
    receipts: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *, transaction_id: str, now: int | None = None,
) -> dict[str, Any]:
    """Correlate credentialed wire receipts across an explicit Agent set.

    Each item is {"authenticated_agent_id": ..., "receipt": ...} supplied
    ONLY by the Controller's credentialed observation dispatcher. A caller
    cannot turn this read-only aggregation into a remote quiescence ACK.
    There is no replay cache or durable host snapshot; even full wire
    correlation is NOT distributed fencing and cannot authorize an update.
    """
    when = int(time.time()) if now is None else now
    failures: set[str] = set()
    expected: set[str] = set()
    seen: set[str] = set()
    nonces: set[str] = set()
    issued_at: int | None = None
    expires_at: int | None = None

    if (type(transaction_id) is not str
            or not _NONCE.fullmatch(transaction_id)
            or not isinstance(expected_agent_ids, (list, tuple))
            or not 1 <= len(expected_agent_ids) <= 64
            or not isinstance(receipts, (list, tuple))
            or len(receipts) > 64):
        failures.add("invalid_expected_scope")
    else:
        for agent_id in expected_agent_ids:
            if type(agent_id) is not str or not _ID.fullmatch(agent_id):
                failures.add("invalid_expected_agent")
            elif agent_id in expected:
                failures.add("duplicate_expected_agent")
            else:
                expected.add(agent_id)
        if len(expected) != len(expected_agent_ids):
            failures.add("incomplete_expected_scope")

    required = {
        "kind", "schema_version", "agent_id", "request_id",
        "transaction_id", "issued_at", "expires_at", "contract",
        "status", "scope", "agent_workers_fenced",
        "remote_agent_quiescence_acked", "live_no_drain_authorized",
    }
    for item in receipts if isinstance(receipts, (list, tuple)) else ():
        if not isinstance(item, Mapping) or set(item) != {
                "authenticated_agent_id", "receipt"}:
            failures.add("receipt_envelope_invalid")
            continue
        agent_id, receipt = item["authenticated_agent_id"], item["receipt"]
        if (type(agent_id) is not str or not _ID.fullmatch(agent_id)
                or agent_id not in expected):
            failures.add("unknown_or_invalid_agent")
            continue
        if agent_id in seen:
            failures.add("duplicate_agent_receipt")
            continue
        seen.add(agent_id)
        if not isinstance(receipt, Mapping) or set(receipt) != required:
            failures.add("receipt_contract_invalid")
            continue
        nonce = receipt.get("request_id")
        issued, expires = receipt.get("issued_at"), receipt.get("expires_at")
        if (type(nonce) is not str or not _NONCE.fullmatch(nonce)
                or nonce in nonces):
            failures.add("receipt_nonce_missing_or_repeated")
        else:
            nonces.add(nonce)
        if (receipt.get("kind") != "CapivaraNoDrainFenceEvidenceReceipt"
                or type(receipt.get("schema_version")) is not int
                or receipt["schema_version"] != 1
                or receipt.get("agent_id") != agent_id
                or receipt.get("transaction_id") != transaction_id
                or receipt.get("contract") != CONTRACT
                or receipt.get("status") != "authenticated_evidence_received_unfenced"
                or receipt.get("scope") != "authenticated_heartbeat_wire_only"
                or receipt.get("agent_workers_fenced") is not False
                or receipt.get("remote_agent_quiescence_acked") is not False
                or receipt.get("live_no_drain_authorized") is not False
                or type(issued) is not int or type(expires) is not int
                or not 0 < issued <= when + 30
                or not issued < expires <= issued + 900
                or not issued <= when < expires):
            failures.add("receipt_transaction_or_lease_invalid")
            continue
        if issued_at is None:
            issued_at, expires_at = issued, expires
        elif (issued_at, expires_at) != (issued, expires):
            failures.add("receipt_lease_mismatch")

    if expected - seen:
        failures.add("expected_agent_receipts_missing")
    try:
        local = observe()
        if (not isinstance(local, Mapping)
                or local.get("active") is not True
                or local.get("reason") != "root_owned_maintenance_hold"
                or local.get("transaction_id") != transaction_id
                or type(local.get("issued_at")) is not int
                or type(local.get("expires_at")) is not int
                or (local["issued_at"], local["expires_at"])
                    != (issued_at, expires_at)):
            failures.add("controller_root_hold_not_correlated")
    except Exception:
        failures.add("controller_root_hold_unavailable")

    complete = not failures and seen == expected
    return {
        "status": ("all_authenticated_wire_receipts_correlated_not_quiesced"
                   if complete else "blocked"),
        "receipt_set_correlated": complete,
        "expected_agent_count": len(expected),
        "observed_agent_count": len(seen),
        "blockers": sorted(failures),
        "installed_process_identity_verified": False,
        "all_runtime_flags_verified": False,
        "all_external_jobs_inventoried": False,
        "external_jobs_acked": False,
        "remote_agents_acked": False,
        "remote_agent_quiescence_acked": False,
        "live_no_drain_authorized": False,
    }
