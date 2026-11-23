#!/usr/bin/env python3
"""#928: persist authenticated NEGATIVE v2 fence receipts before HTTP success.

Called strictly AFTER the Controller verifies the Agent credential. The
root-owned journal's exclusive nonce creation is atomic across Controller
process restarts; no application update, remote ACK, lease recovery or host
identity attestation is implied.

When no privileged journal writer is installed (normal non-root Dashboard),
fail CLOSED rather than accepting an unpersisted negative receipt.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Mapping

_AGENT_RUNTIME = Path(__file__).resolve().parents[1] / "agents/linux/runtime"
if str(_AGENT_RUNTIME) not in sys.path:
    sys.path.append(str(_AGENT_RUNTIME))

from game_uptime_durable_wire_replay import (
    DurableWireReplayBlocked, record_authenticated_negative_receipt,
)


def commit_authenticated_negative_v2_receipt(
    *, authenticated_agent_id: str,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Commit an authenticated negative receipt; never return an ACK.

    The authenticated Agent ID comes ONLY from the credential dispatcher.
    For single-Agent receipt recording, that ID is the exact permitted scope;
    an authoritative cross-host Agent inventory is needed for global quorum.
    """
    if (not isinstance(receipt, Mapping)
            or receipt.get("status") != "authenticated_evidence_received_unfenced"
            or receipt.get("contract") != {
                "protocol": "dsm928-fence-evidence-release-bound-readonly-v2",
                "schema": "2",
            }):
        raise DurableWireReplayBlocked("only_credentialed_negative_v2_can_be_committed")
    journal = record_authenticated_negative_receipt(
        authenticated_agent_id=authenticated_agent_id,
        expected_agent_ids=[authenticated_agent_id],
        receipt=receipt,
        expected_transaction_id=receipt.get("transaction_id"),
        expected_release_sha256=receipt.get("release_sha256"),
    )
    if (journal.get("wire_receipt_received") is not True
            or journal.get("remote_agent_quiescence_acked") is not False
            or journal.get("live_no_drain_authorized") is not False):
        raise DurableWireReplayBlocked("negative_journal_result_untrusted")
    return {
        "status": "negative_v2_receipt_durably_recorded",
        "transaction_id": receipt["transaction_id"],
        "release_sha256": receipt["release_sha256"],
        "request_id": receipt["request_id"],
        "remote_agent_quiescence_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
