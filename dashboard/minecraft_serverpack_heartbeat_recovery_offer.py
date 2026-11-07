#!/usr/bin/env python3
"""Authentication-bound Server Pack recovery receipt over the existing heartbeat.

Only the already authenticated Agent can request an offer for its own
completed provisioning operation. A successful offer is informational and
never authorizes source changes or publishes Agent reports.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from minecraft_serverpack_content_receipt import (
    confirmed_serverpack_receipt, ServerPackControllerReceiptError,
)

_ID = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


def serverpack_recovery_offer(
    backend: Any,
    body: dict[str, Any] | None,
    *,
    authenticated_agent_id: str,
) -> dict[str, Any] | None:
    """Return a read-only Controller receipt for one bounded recovery probe."""
    if not isinstance(body, dict) or "serverpack_recovery_probe" not in body:
        return None
    probe = body["serverpack_recovery_probe"]
    if not isinstance(probe, Mapping):
        return {"status": "rejected", "reason": "invalid_probe"}
    agent = str(authenticated_agent_id or "")
    provisioning_id = probe.get("provisioning_id")
    instance_id = probe.get("instance_id")
    candidate = probe.get("candidate_sha256")
    # All identities are looked up from the database. No Agent identity from
    # the untrusted heartbeat body is used to authorize the request.
    if not (_ID.fullmatch(agent) and isinstance(provisioning_id, str)
            and _ID.fullmatch(provisioning_id)
            and isinstance(instance_id, str) and _ID.fullmatch(instance_id)
            and isinstance(candidate, str) and _SHA.fullmatch(candidate)
            and set(probe) == {"provisioning_id", "instance_id", "candidate_sha256"}):
        return {"status": "rejected", "reason": "invalid_probe"}
    try:
        proof = confirmed_serverpack_receipt(
            backend=backend, provisioning_id=provisioning_id,
            agent_id=agent, instance_id=instance_id,
            candidate_sha256=candidate,
        )
    except (ServerPackControllerReceiptError, KeyError, TypeError, ValueError):
        # The same response is used for unknown and foreign provisioning
        # references: don't disclose the existence of another Agent's job.
        return {"status": "rejected", "reason": "receipt_not_verified"}
    return {
        "kind": "ServerPackRecoveryOffer",
        "status": "verified",
        "provisioning_id": provisioning_id,
        "instance_id": instance_id,
        "candidate_sha256": candidate,
        "bundle_revision": proof["bundle_revision"],
        "manifest_sha256": proof["manifest_sha256"],
        "loader_version": proof["loader_version"],
        "child_count": proof["child_count"],
        "instruction": "verify_local_sources_before_recovery",
    }
