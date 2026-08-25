#!/usr/bin/env python3
"""Persistence for Capivara DSM Customer self-service accounts."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_reference import resolve_customer_reference

VALID_ACCOUNT_ROLES = {"owner", "manager", "member"}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _db_datetime(backend, value: datetime):
    if backend.name == "mysql":
        return value.astimezone(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    if backend.name == "postgresql":
        return value
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class CustomerAccountRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _session(self, connection: Any) -> AlertSession:
        return AlertSession(self.backend, connection)

    @staticmethod
    def _pk(customer_reference: Any) -> int:
        return resolve_customer_reference(customer_reference, public_only=isinstance(customer_reference, str))

    def list_members(self, customer_reference: Any) -> list[dict[str, Any]]:
        customer_id = self._pk(customer_reference)
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
            finally:
                session.close()

    def set_member(self, customer_reference: Any, username: str, account_role: str) -> None:
        customer_id = self._pk(customer_reference)
        if account_role not in VALID_ACCOUNT_ROLES:
            raise ValueError("invalid customer account role")
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                user = session.execute(
                    f"SELECT role,customer_id FROM dashboard_users WHERE username={ph}",
                    (username,),
                ).fetchone()
                if (
                    user is None
                    or user["role"] != "customer"
                    or int(user["customer_id"] or 0) != customer_id
                ):
                    raise ValueError("user is not linked to customer")
                if account_role == "owner":
                    owner = session.execute(
                        f"SELECT username FROM customer_account_members WHERE customer_id={ph} AND account_role='owner' AND username<>{ph}",
                        (customer_id, username),
                    ).fetchone()
                    if owner is not None:
                        raise ValueError("customer already has an owner")
                current = session.execute(
                    f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if current is None:
                    session.execute(
                        "INSERT INTO customer_account_members(customer_id,username,account_role) "
                        f"VALUES ({self.dialect.parameters(3)})",
                        (customer_id, username, account_role),
                    )
                else:
                    session.execute(
                        f"UPDATE customer_account_members SET account_role={ph},updated_at={self.dialect.current_timestamp} WHERE customer_id={ph} AND username={ph}",
                        (account_role, customer_id, username),
                    )
            finally:
                session.close()

    def create_recovery(self, username: str, *, ttl_minutes: int = 30) -> str:
        self.backend.initialize(); ph = self.dialect.placeholder
        token = secrets.token_urlsafe(32); digest = token_digest(token); recovery_id = str(uuid.uuid4())
        expires = datetime.now(timezone.utc) + timedelta(minutes=max(5, min(int(ttl_minutes), 120)))
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                user = session.execute(
                    f"SELECT role,customer_id FROM dashboard_users WHERE username={ph} AND active=TRUE",
                    (username,),
                ).fetchone()
                if user is None or user["role"] != "customer" or user["customer_id"] is None:
                    raise LookupError("customer user not found")
                session.execute(
                    "INSERT INTO customer_password_recovery(id,username,token_hash,expires_at) "
                    f"VALUES ({self.dialect.parameters(4)})",
                    (recovery_id, username, digest, _db_datetime(self.backend, expires)),
                )
            finally:
                session.close()
        return token

    def _recovery_row(self, session, token: str):
        ph = self.dialect.placeholder
        row = session.execute(
            f"SELECT id,username,expires_at,consumed_at FROM customer_password_recovery WHERE token_hash={ph}",
            (token_digest(token),),
        ).fetchone()
        if row is None or row["consumed_at"]:
            raise ValueError("invalid recovery token")
        if _parse_datetime(row["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("expired recovery token")
        return row

    def consume_recovery(self, token: str) -> str:
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = self._recovery_row(session, token)
                session.execute(
                    f"UPDATE customer_password_recovery SET consumed_at={self.dialect.current_timestamp} WHERE id={ph}",
                    (row["id"],),
                )
                return str(row["username"])
            finally:
                session.close()

    def reset_password(self, token: str, password_hash: str) -> str:
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = self._recovery_row(session, token); username = str(row["username"])
                updated = session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},updated_at={self.dialect.current_timestamp} WHERE username={ph} AND role='customer' AND active=TRUE AND customer_id IS NOT NULL",
                    (password_hash, username),
                )
                if getattr(updated, "rowcount", 1) == 0:
                    raise LookupError("customer user not found")
                session.execute(
                    f"UPDATE customer_password_recovery SET consumed_at={self.dialect.current_timestamp} WHERE id={ph}",
                    (row["id"],),
                )
                return username
            finally:
                session.close()
