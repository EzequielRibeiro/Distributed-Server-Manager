#!/usr/bin/env python3
"""Secure credential recovery for an already registered Agent identity."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_pairing_repository import (
    AgentCredentialInvalid,
    EnrolledAgentIdentity,
    PairingTokenConsumed,
    PairingTokenExpired,
    PairingTokenInvalid,
)
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_identity import generate_agent_secret, generate_identity_id, secret_digest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


class AgentRelinkRepository:
    """Rotate an Agent credential after proving a one-time pairing token and identity."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def relink(
        self,
        *,
        pairing_token: str,
        agent_id: str,
        node_id: str,
        fingerprint: str,
        now: datetime | None = None,
    ) -> EnrolledAgentIdentity:
        token = str(pairing_token or "").strip()
        agent_id = str(agent_id or "").strip()
        node_id = str(node_id or "").strip()
        fingerprint = str(fingerprint or "").strip()
        if not all((token, agent_id, node_id, fingerprint)):
            raise ValueError("pairing_token, agent_id, node_id and fingerprint are required")
        current = now or _now()
        ph = self.dialect.placeholder
        token_hash = secret_digest(token)
        credential_id = generate_identity_id("cred")
        credential_secret = generate_agent_secret()

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
                if _parse(token_row["expires_at"]) <= current:
                    raise PairingTokenExpired("pairing token has expired")

                agent = session.execute(
                    "SELECT a.controller_id,a.node_id,a.status,ari.fingerprint "
                    "FROM agents a LEFT JOIN agent_runtime_inventory ari ON ari.agent_id=a.id "
                    f"WHERE a.id={ph}",
                    (agent_id,),
                ).fetchone()
                if agent is None:
                    raise LookupError("Agent not found")
                if str(agent["controller_id"]) != str(token_row["controller_id"]):
                    raise PairingTokenInvalid("pairing token belongs to another Controller")
                if str(agent["node_id"]) != node_id:
                    raise AgentCredentialInvalid("Agent node identity mismatch")
                stored_fingerprint = str(agent["fingerprint"] or "").strip()
                if stored_fingerprint and stored_fingerprint != fingerprint:
                    raise AgentCredentialInvalid("Agent fingerprint mismatch")

                claim = session.execute(
                    f"UPDATE agent_pairing_tokens SET consumed_at={ph} WHERE id={ph} AND consumed_at IS NULL",
                    (_stamp(current), str(token_row["id"])),
                )
                if getattr(claim, "rowcount", 0) != 1:
                    raise PairingTokenConsumed("pairing token has already been consumed")

                session.execute(
                    f"UPDATE agent_credentials SET status='revoked',revoked_at={ph} "
                    f"WHERE agent_id={ph} AND status='active'",
                    (_stamp(current), agent_id),
                )
                session.execute(
                    "INSERT INTO agent_credentials("
                    "id,agent_id,controller_id,credential_type,secret_hash,fingerprint,status"
                    f") VALUES ({self.dialect.parameters(7)})",
                    (
                        credential_id,
                        agent_id,
                        str(agent["controller_id"]),
                        "opaque-v1",
                        secret_digest(credential_secret),
                        fingerprint,
                        "active",
                    ),
                )
                session.execute(
                    f"UPDATE agents SET status='pairing',updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (agent_id,),
                )
            finally:
                session.close()

        return EnrolledAgentIdentity(
            agent_id=agent_id,
            node_id=node_id,
            controller_id=str(agent["controller_id"]),
            status="pairing",
            credential_id=credential_id,
            credential_secret=credential_secret,
            credential_type="opaque-v1",
            fingerprint=fingerprint,
        )
