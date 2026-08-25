#!/usr/bin/env python3
"""Customer account identity helpers for Capivara DSM.

Self-service identity rules stay outside dashboard/server.py. Public Customer
references are resolved to numeric Baseline v2 primary keys before persistence.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_reference import resolve_customer_reference

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SFTP_USERNAME_RE = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")


def normalize_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if not email or len(email) > 320 or not EMAIL_RE.fullmatch(email):
        raise ValueError("invalid customer email")
    return email


def _ascii_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", ascii_value)
    return re.sub(r"[-._]{2,}", "-", slug).strip("-._")


def sftp_username_seed(email: str) -> str:
    normalized = normalize_email(email)
    local_part = normalized.split("@", 1)[0]
    seed = _ascii_slug(local_part) or "user"
    if not seed[0].isalpha():
        seed = f"u-{seed}"
    seed = seed[:32].rstrip("-._")
    if len(seed) < 3:
        seed = (seed + "-user")[:32]
    if not SFTP_USERNAME_RE.fullmatch(seed):
        raise ValueError("unable to derive SFTP username from email")
    return seed


def collision_suffix(email: str, attempt: int = 0) -> str:
    normalized = normalize_email(email)
    material = normalized if attempt == 0 else f"{normalized}:{attempt}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


class CustomerIdentityService:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _username_exists(self, session: AlertSession, username: str) -> bool:
        ph = self.dialect.placeholder
        return session.execute(
            f"SELECT 1 FROM customers WHERE sftp_username={ph}", (username,)
        ).fetchone() is not None

    def allocate_sftp_username(self, session: AlertSession, email: str) -> str:
        seed = sftp_username_seed(email)
        if not self._username_exists(session, seed):
            return seed
        for attempt in range(100):
            suffix = collision_suffix(email, attempt)
            prefix = seed[: 32 - len(suffix) - 1].rstrip("-._")
            candidate = f"{prefix}-{suffix}"
            if not self._username_exists(session, candidate):
                return candidate
        raise RuntimeError("unable to allocate unique SFTP username")

    def assign_identity(self, customer_reference: Any, email: str) -> dict[str, str]:
        self.backend.initialize()
        customer_id = resolve_customer_reference(
            customer_reference,
            public_only=isinstance(customer_reference, str),
        )
        normalized = normalize_email(email)
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT account_email,sftp_username FROM customers " f"WHERE id={ph}",
                    (customer_id,),
                ).fetchone()
                if row is None:
                    raise LookupError("customer not found")
                if row["account_email"] and row["sftp_username"]:
                    return {
                        "account_email": row["account_email"],
                        "sftp_username": row["sftp_username"],
                    }
                duplicate = session.execute(
                    "SELECT id FROM customers WHERE LOWER(account_email)="
                    f"LOWER({ph}) AND id<>{ph}",
                    (normalized, customer_id),
                ).fetchone()
                if duplicate is not None:
                    raise ValueError("customer account email already registered")
                username = self.allocate_sftp_username(session, normalized)
                session.execute(
                    f"UPDATE customers SET account_email={ph},sftp_username={ph},"
                    f"updated_at={self.dialect.current_timestamp} WHERE id={ph}",
                    (normalized, username, customer_id),
                )
                return {"account_email": normalized, "sftp_username": username}
            finally:
                session.close()
