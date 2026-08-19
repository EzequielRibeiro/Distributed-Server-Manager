#!/usr/bin/env python3
"""Persistence for Capivara DSM customer self-service accounts."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend

VALID_ACCOUNT_ROLES = {"owner", "manager", "member"}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CustomerAccountRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _session(self, connection: Any) -> AlertSession:
        return AlertSession(self.backend, connection)

    def list_members(self, customer_id: str) -> list[dict[str, Any]]:
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT m.username,m.account_role,u.active,m.created_at,m.updated_at "
                    "FROM customer_account_members m JOIN dashboard_users u ON u.username=m.username "
                    f"WHERE m.customer_id={ph} ORDER BY CASE m.account_role WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END,m.username",
                    (customer_id,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally: session.close()

    def set_member(self, customer_id: str, username: str, account_role: str) -> None:
        if account_role not in VALID_ACCOUNT_ROLES: raise ValueError("invalid customer account role")
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                user = session.execute(
                    f"SELECT role,scope_id FROM dashboard_users WHERE username={ph}", (username,)
                ).fetchone()
                if user is None or user["role"] != "customer" or user["scope_id"] != customer_id:
                    raise ValueError("user is not linked to customer")
                if account_role == "owner":
                    owner = session.execute(
                        f"SELECT username FROM customer_account_members WHERE customer_id={ph} AND account_role='owner' AND username<>{ph}",
                        (customer_id, username),
                    ).fetchone()
                    if owner is not None: raise ValueError("customer already has an owner")
                current = session.execute(
                    f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if current is None:
                    session.execute(
                        "INSERT INTO customer_account_members(customer_id,username,account_role) "
                        f"VALUES ({self.dialect.parameters(3)})", (customer_id, username, account_role)
                    )
                else:
                    session.execute(
                        f"UPDATE customer_account_members SET account_role={ph},updated_at={self.dialect.current_timestamp} "
                        f"WHERE customer_id={ph} AND username={ph}", (account_role, customer_id, username)
                    )
            finally: session.close()

    def create_recovery(self, username: str, *, ttl_minutes: int = 30) -> str:
        self.backend.initialize(); ph = self.dialect.placeholder
        token = secrets.token_urlsafe(32); digest = token_digest(token)
        recovery_id = str(uuid.uuid4())
        expires = datetime.now(timezone.utc) + timedelta(minutes=max(5, min(int(ttl_minutes), 120)))
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                user = session.execute(
                    f"SELECT role FROM dashboard_users WHERE username={ph} AND active=TRUE", (username,)
                ).fetchone()
                if user is None or user["role"] != "customer": raise LookupError("customer user not found")
                session.execute(
                    "INSERT INTO customer_password_recovery(id,username,token_hash,expires_at) "
                    f"VALUES ({self.dialect.parameters(4)})",
                    (recovery_id, username, digest, expires.isoformat()),
                )
            finally: session.close()
        return token

    def consume_recovery(self, token: str) -> str:
        self.backend.initialize(); ph = self.dialect.placeholder; digest = token_digest(token)
        now = datetime.now(timezone.utc)
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT id,username,expires_at,consumed_at FROM customer_password_recovery WHERE token_hash={ph}",
                    (digest,),
                ).fetchone()
                if row is None or row["consumed_at"]: raise ValueError("invalid recovery token")
                expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
                if expires.tzinfo is None: expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now: raise ValueError("expired recovery token")
                session.execute(
                    f"UPDATE customer_password_recovery SET consumed_at={self.dialect.current_timestamp} WHERE id={ph}",
                    (row["id"],),
                )
                return str(row["username"])
            finally: session.close()
