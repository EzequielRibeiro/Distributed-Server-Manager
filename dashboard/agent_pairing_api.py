#!/usr/bin/env python3
"""Transport-neutral secure Controller <-> Agent pairing API."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_install_command import linux_agent_install_command
from agent_pairing_repository import AgentPairingRepository


def _role(user: dict[str, Any] | None) -> str:
    if not user:
        raise PermissionError("authentication required")
    return str(user.get("role", "")).strip().lower()


def _controller_scope(user: dict[str, Any], requested: str | None) -> str:
    role = _role(user)
    requested_id = str(requested or "").strip()
    if role == "admin":
        if not requested_id:
            raise ValueError("controller_id is required")
        return requested_id
    if role == "controller":
        scope_id = str(user.get("scope_id", "")).strip()
        if not scope_id:
            raise PermissionError("controller scope is required")
        if requested_id and requested_id != scope_id:
            raise PermissionError("controller is outside user scope")
        return scope_id
    raise PermissionError("Agent pairing administration is not permitted")


def issue_pairing_token_for_user(
    user: dict[str, Any] | None,
    backend,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Issue a short-lived one-time token. Plaintext is returned only now."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    controller_id = _controller_scope(user or {}, payload.get("controller_id"))
    ttl = int(payload.get("ttl_seconds", 900) or 900)
    issued = AgentPairingRepository(backend).issue_token(
        controller_id=controller_id,
        created_by=str((user or {}).get("username", "")).strip() or None,
        ttl_seconds=ttl,
    )
    result = {
        "controller_id": issued.controller_id,
        "pairing_token": issued.token,
        "expires_at": issued.expires_at,
        "one_time": True,
    }
    controller_url = str(payload.get("controller_url", "")).strip()
    if controller_url:
        controller_url = controller_url.rstrip("/")
        result["controller_url"] = controller_url
        result["install_command"] = linux_agent_install_command(
            controller_url=controller_url,
            pairing_token=issued.token,
        )
    return result


def enroll_remote_agent(backend, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Exchange a valid pairing token for permanent Agent credentials."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    identity = AgentPairingRepository(backend).enroll(
        pairing_token=str(payload.get("pairing_token", "")),
        agent_id=str(payload.get("agent_id", "")),
        node_id=str(payload.get("node_id", "")),
        name=str(payload.get("name", "")),
        fingerprint=str(payload.get("fingerprint", "")),
        hostname=payload.get("hostname"),
        os_name=payload.get("os"),
        architecture=payload.get("architecture"),
        capivara_version=payload.get("capivara_version"),
        address=payload.get("address"),
        public_key=payload.get("public_key"),
    )
    return {
        "agent_id": identity.agent_id,
        "node_id": identity.node_id,
        "controller_id": identity.controller_id,
        "status": identity.status,
        "identity": {
            "credential_id": identity.credential_id,
            "credential_secret": identity.credential_secret,
            "credential_type": identity.credential_type,
            "fingerprint": identity.fingerprint,
        },
        "pairing_token_consumed": True,
    }


def authenticate_agent_identity(
    backend,
    *,
    credential_id: str,
    credential_secret: str,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Authenticate a previously enrolled Agent without a pairing token."""
    return AgentPairingRepository(backend).authenticate(
        credential_id=credential_id,
        credential_secret=credential_secret,
        fingerprint=fingerprint,
    )


def revoke_agent_identity_for_user(
    user: dict[str, Any] | None,
    backend,
    *,
    controller_id: str,
    credential_id: str,
) -> dict[str, Any]:
    scoped = _controller_scope(user or {}, controller_id)
    repository = AgentPairingRepository(backend)
    ph = repository.dialect.placeholder
    with backend.connect() as connection:
        from alert_repository import AlertSession
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT controller_id,agent_id FROM agent_credentials WHERE id={ph}",
                (credential_id,),
            ).fetchone()
        finally:
            session.close()
    if row is None:
        raise LookupError("Agent credential not found")
    if str(row["controller_id"]) != scoped:
        raise PermissionError("Agent credential is outside user scope")
    repository.revoke(credential_id)
    return {"credential_id": credential_id, "agent_id": str(row["agent_id"]), "status": "revoked"}
