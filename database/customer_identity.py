#!/usr/bin/env python3
"""Customer account identity helpers for Capivara DSM.

This module keeps customer self-service identity rules outside dashboard/server.py.
It provides deterministic, Linux-safe SFTP username seeds derived from the
customer e-mail address and collision-safe allocation against the database.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


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
    slug = re.sub(r"[-._]{2,}", "-", slug).strip("-._")
    return slug


def sftp_username_seed(email: str) -> str:
    """Return a stable Linux-safe username seed based on the e-mail local part."""
    normalized = normalize_email(email)
    local_part = normalized.split("@", 1)[0]
    seed = _ascii_slug(local_part)
    if not seed:
        seed = "user"
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
    """Backend-independent customer account identity operations."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _username_exists(self, session: AlertSession, username: str) -> bool:
        ph = self.dialect.placeholder
        row = session.execute(
            f"SELECT 1 FROM customers WHERE sftp_username={ph}",
            (username,),
        ).fetchone()
        return row is not None

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

    def assign_identity(self, customer_id: str, email: str) -> dict[str, str]:
        """Assign normalized account e-mail and generated SFTP username.

        Existing identities are returned unchanged, making the operation
        idempotent for registration workflows.
        """
        self.backend.initialize()
        customer_id = str(customer_id or "").strip()
        if not customer_id:
            raise ValueError("customer id is required")
        normalized = normalize_email(email)
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT account_email,sftp_username FROM customers "
                    f"WHERE id={ph}",
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
