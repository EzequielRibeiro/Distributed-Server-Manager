#!/usr/bin/env python3
"""Authenticated Agent service facade using permanent credentials."""

from __future__ import annotations

from typing import Any

from agent_heartbeat_api import record_agent_heartbeat
from agent_pairing_api import authenticate_agent_identity
from agent_uninstall_repository import AgentUninstallRepository


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
    Remote uninstall is exchanged only after permanent Agent authentication,
    and uses a typed state machine rather than arbitrary shell execution.
    """
    identity = authenticate_agent_identity(
        backend,
        credential_id=credential_id,
        credential_secret=credential_secret,
        fingerprint=fingerprint,
    )
    agent_id = str(identity["agent_id"])
    body = payload if isinstance(payload, dict) else {}
    uninstall = AgentUninstallRepository(backend)
    reported = body.get("uninstall_result")
    uninstall_state = uninstall.apply_result(agent_id, reported if isinstance(reported, dict) else None)

    response = record_agent_heartbeat(
        agent_id,
        body,
        backend=backend,
    )
    command = uninstall.command_for_agent(agent_id)
    if command is not None:
        response["uninstall_command"] = command
    state = uninstall_state or uninstall.state(agent_id)
    if state is not None:
        response["uninstall_state"] = state
    return response
