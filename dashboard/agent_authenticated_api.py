#!/usr/bin/env python3
"""Authenticated Agent service facade using permanent credentials."""

from __future__ import annotations

from typing import Any

from agent_heartbeat_api import record_agent_heartbeat
from agent_log_event_repository import AgentLogEventRepository, redact_log_text
from agent_pairing_api import authenticate_agent_identity
from agent_uninstall_repository import AgentUninstallRepository


def _ingest_agent_logs_best_effort(backend, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Persist the overlapping Agent log window without making heartbeat depend on it."""
    logs = body.get("agent_logs")
    if not isinstance(logs, list):
        return {"accepted": 0, "created": 0, "rejected": 0, "status": "not-reported"}
    try:
        repository = AgentLogEventRepository(backend)
        repository.initialize()
        result = repository.ingest_agent_logs(agent_id, logs)
        return {**result, "status": "ok"}
    except Exception as exc:
        # This ledger is diagnostic evidence. Losing one ingestion attempt must
        # never prevent inventory, runtime state or last_seen from advancing.
        return {
            "accepted": 0,
            "created": 0,
            "rejected": 0,
            "status": "failed-open",
            "error": type(exc).__name__,
        }


def _heartbeat_payload_with_redacted_logs(body: dict[str, Any]) -> dict[str, Any]:
    """Keep transient raw logs out of metadata_json while preserving other fields."""
    logs = body.get("agent_logs")
    if not isinstance(logs, list):
        return body
    safe = dict(body)
    safe["agent_logs"] = [
        redact_log_text(item)[:2000]
        for item in logs[-200:]
        if isinstance(item, str)
    ]
    return safe


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

    # Ingest the original representation first so the event fingerprint remains
    # stable. Only the redacted copy may flow into agents.metadata_json.
    log_ingestion = _ingest_agent_logs_best_effort(backend, agent_id, body)
    heartbeat_body = _heartbeat_payload_with_redacted_logs(body)

    uninstall = AgentUninstallRepository(backend)
    reported = body.get("uninstall_result")
    uninstall_state = uninstall.apply_result(
        agent_id,
        reported if isinstance(reported, dict) else None,
    )

    response = record_agent_heartbeat(
        agent_id,
        heartbeat_body,
        backend=backend,
    )
    response["agent_logs_accepted"] = int(log_ingestion.get("accepted", 0))
    response["agent_logs_created"] = int(log_ingestion.get("created", 0))
    response["agent_logs_rejected"] = int(log_ingestion.get("rejected", 0))
    response["agent_logs_ingestion_status"] = str(
        log_ingestion.get("status") or "unknown"
    )
    command = uninstall.command_for_agent(agent_id)
    if command is not None:
        response["uninstall_command"] = command
    state = uninstall_state or uninstall.state(agent_id)
    if state is not None:
        response["uninstall_state"] = state
    return response
