#!/usr/bin/env python3
"""Authenticated Agent service facade using permanent credentials."""

from __future__ import annotations

from typing import Any

from agent_heartbeat_api import record_agent_heartbeat
from agent_pairing_api import authenticate_agent_identity


def authenticated_agent_heartbeat(
    backend,
    *,
    credential_id: str,
    credential_secret: str,
    payload: dict[str, Any] | None,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Authenticate the permanent Agent identity, then record its heartbeat.

    Pairing tokens are deliberately not accepted by this API.
    """
    identity = authenticate_agent_identity(
        backend,
        credential_id=credential_id,
        credential_secret=credential_secret,
        fingerprint=fingerprint,
    )
    return record_agent_heartbeat(
        identity["agent_id"],
        payload,
        backend=backend,
    )
