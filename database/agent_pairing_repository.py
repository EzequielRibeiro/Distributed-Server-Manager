#!/usr/bin/env python3
"""Secure one-time Agent enrollment and permanent credential persistence."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.agent_identity import (
    generate_agent_secret,
    generate_identity_id,
    generate_pairing_token,
    secret_digest,
    secrets_match,
)
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class PairingTokenInvalid(PermissionError):
    pass


class PairingTokenExpired(PermissionError):
    pass


class PairingTokenConsumed(PermissionError):
    pass


class PairingRegistrationConflict(ValueError):
    pass


class AgentCredentialInvalid(PermissionError):
    pass


@dataclass(frozen=True)
class IssuedPairingToken:
    token_id: str
    controller_id: str
    token: str
    expires_at: str


@dataclass(frozen=True)
class EnrolledAgentIdentity:
    agent_id: str
    node_id: str
    controller_id: str
    status: str
    credential_id: str
    credential_secret: str
    credential_type: str
    fingerprint: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


class AgentPairingRepository:
    """Issue one-time tokens and exchange them for permanent Agent identity."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    def issue_token(
        self,
        *,
        controller_id: str,
        created_by: str | None = None,
        ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> IssuedPairingToken:
        controller_id = str(controller_id).strip()
        if not controller_id:
            raise ValueError("controller_id is required")
        if ttl_seconds < 60 or ttl_seconds > 86400:
            raise ValueError("ttl_seconds must be between 60 and 86400")

        current = now or _utc_now()
        expires = current + timedelta(seconds=ttl_seconds)
        token = generate_pairing_token()
        token_id = generate_identity_id("pair")
        ph = self.dialect.placeholder

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                controller = session.execute(
                    f"SELECT status FROM controllers WHERE id={ph}",
                    (controller_id,),
                ).fetchone()
                if controller is None:
                    raise LookupError(f"Controller not found: {controller_id}")
                if str(controller["status"]).strip().lower() != "active":
                    raise ValueError("Controller must be active to issue pairing tokens")
                session.execute(
                    "INSERT INTO agent_pairing_tokens("
                    "id,controller_id,token_hash,expires_at,created_by"
                    f") VALUES ({self.dialect.parameters(5)})",
                    (
                        token_id,
                        controller_id,
                        secret_digest(token),
                        _timestamp(expires),
                        str(created_by or "").strip() or None,
                    ),
                )
            finally:
                session.close()

        return IssuedPairingToken(token_id, controller_id, token, _timestamp(expires))

    def enroll(
        self,
        *,
        pairing_token: str,
        agent_id: str,
        node_id: str,
        name: str,
        fingerprint: str,
        hostname: str | None = None,
        os_name: str | None = None,
        architecture: str | None = None,
        capivara_version: str | None = None,
        address: str | None = None,
        public_key: str | None = None,
        now: datetime | None = None,
    ) -> EnrolledAgentIdentity:
        token = str(pairing_token).strip()
        agent_id = str(agent_id).strip()
        node_id = str(node_id).strip()
        name = str(name).strip()
        fingerprint = str(fingerprint).strip()
        if not all((token, agent_id, node_id, name, fingerprint)):
            raise ValueError("pairing_token, agent_id, node_id, name and fingerprint are required")

        current = now or _utc_now()
        ph = self.dialect.placeholder
        permanent_secret = generate_agent_secret()
        credential_id = generate_identity_id("cred")
        token_hash = secret_digest(token)

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                token_row = session.execute(
                    "SELECT id,controller_id,expires_at,consumed_at FROM agent_pairing_tokens "
                    f"WHERE token_hash={ph}",
                    (token_hash,),
                ).fetchone()
                if token_row is None:
                    raise PairingTokenInvalid("invalid pairing token")
                if token_row["consumed_at"]:
                    raise PairingTokenConsumed("pairing token has already been consumed")
                if _parse_timestamp(str(token_row["expires_at"])) <= current:
                    raise PairingTokenExpired("pairing token has expired")

                claim = session.execute(
                    f"UPDATE agent_pairing_tokens SET consumed_at={ph} "
                    f"WHERE id={ph} AND consumed_at IS NULL",
                    (_timestamp(current), str(token_row["id"])),
                )
                if getattr(claim, "rowcount", 0) != 1:
                    raise PairingTokenConsumed("pairing token has already been consumed")

                controller_id = str(token_row["controller_id"])
                controller = session.execute(
                    f"SELECT status FROM controllers WHERE id={ph}",
                    (controller_id,),
                ).fetchone()
                if controller is None or str(controller["status"]).strip().lower() != "active":
                    raise PairingTokenInvalid("pairing Controller is unavailable")

                if session.execute(f"SELECT 1 FROM agents WHERE id={ph}", (agent_id,)).fetchone():
                    raise PairingRegistrationConflict("agent_id is already registered")
                if session.execute(f"SELECT 1 FROM nodes WHERE id={ph}", (node_id,)).fetchone():
                    raise PairingRegistrationConflict("node_id is already registered")

                session.execute(
                    "INSERT INTO nodes(id,name,role,status,metadata_json) "
                    f"VALUES ({self.dialect.parameters(5)})",
                    (node_id, name, "agent", "pending", "{}"),
                )
                session.execute(
                    "INSERT INTO agents(id,controller_id,node_id,name,status,metadata_json) "
                    f"VALUES ({self.dialect.parameters(6)})",
                    (agent_id, controller_id, node_id, name, "pairing", "{}"),
                )
                session.execute(
                    "INSERT INTO agent_runtime_inventory("
                    "agent_id,hostname,os_name,architecture,capivara_version,address,fingerprint"
                    f") VALUES ({self.dialect.parameters(7)})",
                    (agent_id, hostname, os_name, architecture, capivara_version, address, fingerprint),
                )
                session.execute(
                    "INSERT INTO agent_credentials("
                    "id,agent_id,controller_id,credential_type,secret_hash,fingerprint,public_key"
                    f") VALUES ({self.dialect.parameters(7)})",
                    (
                        credential_id,
                        agent_id,
                        controller_id,
                        "opaque-v1",
                        secret_digest(permanent_secret),
                        fingerprint,
                        str(public_key).strip() if public_key else None,
                    ),
                )
            finally:
                session.close()

        return EnrolledAgentIdentity(
            agent_id=agent_id,
            node_id=node_id,
            controller_id=controller_id,
            status="pairing",
            credential_id=credential_id,
            credential_secret=permanent_secret,
            credential_type="opaque-v1",
            fingerprint=fingerprint,
        )

    def authenticate(
        self,
        *,
        credential_id: str,
        credential_secret: str,
        fingerprint: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        credential_id = str(credential_id).strip()
        secret = str(credential_secret).strip()
        if not credential_id or not secret:
            raise AgentCredentialInvalid("Agent credential is required")
        ph = self.dialect.placeholder
        current = now or _utc_now()

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT c.agent_id,c.controller_id,c.secret_hash,c.fingerprint,c.status,a.status AS agent_status "
                    "FROM agent_credentials c JOIN agents a ON a.id=c.agent_id "
                    f"WHERE c.id={ph}",
                    (credential_id,),
                ).fetchone()
                if row is None or str(row["status"]) != "active":
                    raise AgentCredentialInvalid("invalid Agent credential")
                if str(row["agent_status"] or "").strip().lower() == "decommissioned":
                    raise AgentCredentialInvalid("decommissioned Agent cannot authenticate")
                expected = str(row["secret_hash"] or "")
                if not expected or not secrets_match(secret, expected):
                    raise AgentCredentialInvalid("invalid Agent credential")
                if fingerprint and str(fingerprint).strip() != str(row["fingerprint"]):
                    raise AgentCredentialInvalid("Agent fingerprint mismatch")
                session.execute(
                    f"UPDATE agent_credentials SET last_used_at={ph} WHERE id={ph}",
                    (_timestamp(current), credential_id),
                )
                return {
                    "agent_id": str(row["agent_id"]),
                    "controller_id": str(row["controller_id"]),
                    "role": "agent",
                    "status": str(row["agent_status"]),
                    "credential_id": credential_id,
                }
            finally:
                session.close()

    def revoke(self, credential_id: str, *, now: datetime | None = None) -> None:
        credential_id = str(credential_id).strip()
        if not credential_id:
            raise ValueError("credential_id is required")
        ph = self.dialect.placeholder
        current = now or _utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT 1 FROM agent_credentials WHERE id={ph}",
                    (credential_id,),
                ).fetchone()
                if row is None:
                    raise LookupError("Agent credential not found")
                session.execute(
                    f"UPDATE agent_credentials SET status='revoked',revoked_at={ph} WHERE id={ph}",
                    (_timestamp(current), credential_id),
                )
            finally:
                session.close()
