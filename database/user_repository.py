#!/usr/bin/env python3
"""Backend-independent dashboard user persistence."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_reference import resolve_customer_reference


class UserRepository:
    """Persist dashboard users through a DatabaseBackend."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(self, *, transaction: bool = False) -> Iterator[AlertSession]:
        context = self.backend.transaction() if transaction else self.backend.connect()
        with context as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def get(self, username: str) -> dict[str, Any] | None:
        self.initialize()
        with self.session() as session:
            row = session.execute(
                "SELECT * FROM dashboard_users WHERE username=" + self.dialect.placeholder,
                (username.strip().lower(),),
            ).fetchone()
        return None if row is None else dict(row)

    def list_users(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.session() as session:
            rows = session.execute(
                "SELECT username,role,scope_id,customer_id,active "
                "FROM dashboard_users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def save(
        self,
        *,
        username: str,
        password_hash: str,
        role: str,
        scope_id: str | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Save one dashboard login.

        `scope_id` remains the CLI compatibility argument. For Customer users it
        must be a public `CLI-NNNNNN` code and is resolved into the dedicated
        numeric `dashboard_users.customer_id`; Customer codes are never persisted
        in the generic scope column.
        """
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        generic_scope = scope_id
        customer_id = None
        with self.session(transaction=True) as session:
            if role == "controller":
                if session.execute(
                    f"SELECT 1 FROM controllers WHERE id={ph}", (scope_id,)
                ).fetchone() is None:
                    raise ValueError("scope does not exist")
            elif role == "customer":
                customer_id = resolve_customer_reference(scope_id, public_only=True)
                generic_scope = None
                if session.execute(
                    f"SELECT 1 FROM customers WHERE id={ph}", (customer_id,)
                ).fetchone() is None:
                    raise ValueError("scope does not exist")
            else:
                generic_scope = None

            current = session.execute(
                f"SELECT 1 FROM dashboard_users WHERE username={ph}", (username,)
            ).fetchone()
            if current is not None and not replace:
                raise ValueError("user already exists")
            active_value = True if self.backend.name == "postgresql" else 1
            if current is None:
                session.execute(
                    "INSERT INTO dashboard_users(username,password_hash,role,scope_id,customer_id,active) "
                    f"VALUES ({self.dialect.parameters(6)})",
                    (
                        username,
                        password_hash,
                        role,
                        generic_scope,
                        customer_id,
                        active_value,
                    ),
                )
            else:
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},role={ph},scope_id={ph},"
                    f"customer_id={ph},active={ph},updated_at={now} WHERE username={ph}",
                    (
                        password_hash,
                        role,
                        generic_scope,
                        customer_id,
                        active_value,
                        username,
                    ),
                )
        result = self.get(username)
        assert result is not None
        return result

    def change_password(self, username: str, password_hash: str) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            cursor = session.execute(
                f"UPDATE dashboard_users SET password_hash={ph},"
                f"updated_at={self.dialect.current_timestamp} WHERE username={ph}",
                (password_hash, username),
            )
            if not cursor.rowcount:
                raise ValueError("usuário não encontrado")

    def delete(self, username: str) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            row = session.execute(
                f"SELECT role FROM dashboard_users WHERE username={ph}", (username,)
            ).fetchone()
            if row is None:
                raise ValueError("user not found")
            if row["role"] == "admin":
                active = "TRUE" if self.backend.name == "postgresql" else "1"
                count = session.execute(
                    "SELECT COUNT(*) AS total FROM dashboard_users "
                    f"WHERE role='admin' AND active={active}"
                ).fetchone()
                if int(count["total"]) <= 1:
                    raise ValueError("cannot delete the last active administrator")
            session.execute(
                f"DELETE FROM dashboard_users WHERE username={ph}", (username,)
            )

    def close(self) -> None:
        self.backend.close()
