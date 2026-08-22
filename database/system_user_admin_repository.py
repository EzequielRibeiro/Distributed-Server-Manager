#!/usr/bin/env python3
"""Administrative system-user lifecycle and temporary credential state."""
from __future__ import annotations

import re
import secrets
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from users import hash_password

SYSTEM_ROLES = {"admin", "controller", "operator"}
_USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")


class SystemUserAdminRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _session(self, connection) -> AlertSession:
        return AlertSession(self.backend, connection)

    def initialize(self) -> None:
        self.backend.initialize()
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                session.execute(
                    "CREATE TABLE IF NOT EXISTS system_password_state ("
                    "username VARCHAR(128) PRIMARY KEY,"
                    "must_change_password INTEGER NOT NULL DEFAULT 0,"
                    "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            finally:
                session.close()

    def list_users(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT u.username,u.role,u.scope_id,u.active,"
                    "COALESCE(ps.must_change_password,0) AS must_change_password "
                    "FROM dashboard_users u LEFT JOIN system_password_state ps ON ps.username=u.username "
                    "WHERE u.role IN ('admin','controller','operator') ORDER BY u.username"
                ).fetchall()
            finally:
                session.close()
        result = []
        for row in rows:
            item = dict(row)
            item["active"] = bool(item.get("active"))
            item["must_change_password"] = bool(int(item.get("must_change_password") or 0))
            result.append(item)
        return result

    def password_change_required(self, username: str) -> bool:
        self.initialize()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT must_change_password FROM system_password_state WHERE username={ph}",
                    (str(username or "").strip().lower(),),
                ).fetchone()
            finally:
                session.close()
        return bool(row and int(row["must_change_password"] or 0))

    def save_user(self, *, actor: str, username: str, role: str, scope_id: str | None,
                  active: bool, password: str | None = None) -> dict[str, Any]:
        self.initialize()
        username = str(username or "").strip().lower()
        role = str(role or "").strip().lower()
        actor = str(actor or "").strip().lower()
        if not _USERNAME_RE.fullmatch(username):
            raise ValueError("invalid username")
        if role not in SYSTEM_ROLES:
            raise ValueError("invalid system role")
        if role == "controller" and not scope_id:
            raise ValueError("controller users require a controller scope")
        if role in {"admin", "operator"}:
            scope_id = None
        ph = self.dialect.placeholder
        generated = None
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                existing = session.execute(
                    f"SELECT username,password_hash,role,scope_id,active FROM dashboard_users WHERE username={ph}",
                    (username,),
                ).fetchone()
                if existing is not None and str(existing["role"]) == "customer":
                    raise ValueError("customer users must be managed in the Customers area")
                if role == "controller":
                    if session.execute(f"SELECT 1 FROM controllers WHERE id={ph}", (scope_id,)).fetchone() is None:
                        raise ValueError("controller scope does not exist")
                if actor == username and (role != "admin" or not active):
                    raise ValueError("the current administrator cannot remove its own access")
                if existing is None and not password:
                    generated = self._temporary_password()
                    password = generated
                if password is not None and len(password) < 8:
                    raise ValueError("password must have at least 8 characters")
                password_hash = hash_password(password) if password else str(existing["password_hash"])
                projected = {
                    str(row["username"]): {"role": str(row["role"]), "active": bool(row["active"])}
                    for row in session.execute(
                        "SELECT username,role,active FROM dashboard_users WHERE role IN ('admin','controller','operator')"
                    ).fetchall()
                }
                projected[username] = {"role": role, "active": bool(active)}
                if not any(item["role"] == "admin" and item["active"] for item in projected.values()):
                    raise ValueError("at least one active administrator is required")
                if existing is None:
                    session.execute(
                        "INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) "
                        f"VALUES ({self.dialect.parameters(5)})",
                        (username, password_hash, role, scope_id, bool(active)),
                    )
                else:
                    session.execute(
                        f"UPDATE dashboard_users SET password_hash={ph},role={ph},scope_id={ph},active={ph},"
                        f"updated_at={self.dialect.current_timestamp} WHERE username={ph}",
                        (password_hash, role, scope_id, bool(active), username),
                    )
                if password:
                    self._set_password_state(session, username, True)
            finally:
                session.close()
        return {
            "username": username,
            "role": role,
            "scope_id": scope_id,
            "active": bool(active),
            "must_change_password": bool(password),
            "temporary_password": generated,
        }

    def reset_password(self, username: str) -> dict[str, Any]:
        self.initialize()
        username = str(username or "").strip().lower()
        ph = self.dialect.placeholder
        temporary_password = self._temporary_password()
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT role FROM dashboard_users WHERE username={ph}", (username,)
                ).fetchone()
                if row is None or str(row["role"]) not in SYSTEM_ROLES:
                    raise ValueError("system user not found")
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},updated_at={self.dialect.current_timestamp} WHERE username={ph}",
                    (hash_password(temporary_password), username),
                )
                self._set_password_state(session, username, True)
            finally:
                session.close()
        return {"username": username, "temporary_password": temporary_password, "must_change_password": True}

    def change_temporary_password(self, username: str, new_password: str) -> None:
        self.initialize()
        username = str(username or "").strip().lower()
        if len(str(new_password or "")) < 8:
            raise ValueError("password must have at least 8 characters")
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(f"SELECT role FROM dashboard_users WHERE username={ph}", (username,)).fetchone()
                if row is None or str(row["role"]) not in SYSTEM_ROLES:
                    raise ValueError("system user not found")
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},updated_at={self.dialect.current_timestamp} WHERE username={ph}",
                    (hash_password(new_password), username),
                )
                self._set_password_state(session, username, False)
            finally:
                session.close()

    def _set_password_state(self, session: AlertSession, username: str, required: bool) -> None:
        ph = self.dialect.placeholder
        value = 1 if required else 0
        exists = session.execute(
            f"SELECT 1 FROM system_password_state WHERE username={ph}", (username,)
        ).fetchone()
        if exists:
            session.execute(
                f"UPDATE system_password_state SET must_change_password={ph},updated_at={self.dialect.current_timestamp} WHERE username={ph}",
                (value, username),
            )
        else:
            session.execute(
                "INSERT INTO system_password_state(username,must_change_password) "
                f"VALUES ({self.dialect.parameters(2)})", (username, value),
            )

    @staticmethod
    def _temporary_password() -> str:
        return secrets.token_urlsafe(12)


__all__ = ["SYSTEM_ROLES", "SystemUserAdminRepository"]
