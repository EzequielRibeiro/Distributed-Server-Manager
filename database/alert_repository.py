#!/usr/bin/env python3
"""Backend-independent alert persistence primitives for Capivara DSM."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Mapping, Sequence

from backend import DatabaseBackend, DatabaseConfigurationError


@dataclass(frozen=True)
class AlertSQLDialect:
    """Small SQL differences used by alert persistence."""

    name: str
    placeholder: str
    current_timestamp: str

    def parameters(self, count: int) -> str:
        return ",".join(self.placeholder for _ in range(count))

    def pagination(
        self,
        *,
        limit: int | None,
        offset: int,
    ) -> tuple[str, list[int]]:
        if limit is not None:
            sql = f" LIMIT {self.placeholder}"
            values = [limit]

            if offset:
                sql += f" OFFSET {self.placeholder}"
                values.append(offset)

            return sql, values

        if not offset:
            return "", []

        if self.name == "sqlite":
            return f" LIMIT -1 OFFSET {self.placeholder}", [offset]

        if self.name == "mysql":
            return (
                " LIMIT 18446744073709551615"
                f" OFFSET {self.placeholder}",
                [offset],
            )

        return f" OFFSET {self.placeholder}", [offset]


DIALECTS = {
    "sqlite": AlertSQLDialect(
        name="sqlite",
        placeholder="?",
        current_timestamp=(
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        ),
    ),
    "postgresql": AlertSQLDialect(
        name="postgresql",
        placeholder="%s",
        current_timestamp="CURRENT_TIMESTAMP",
    ),
    "mysql": AlertSQLDialect(
        name="mysql",
        placeholder="%s",
        current_timestamp="CURRENT_TIMESTAMP(6)",
    ),
}


def dialect_for_backend(
    backend: DatabaseBackend,
) -> AlertSQLDialect:
    """Return the SQL dialect associated with a backend."""

    try:
        return DIALECTS[backend.name]

    except KeyError as exc:
        raise DatabaseConfigurationError(
            f"unsupported alert repository backend: {backend.name}"
        ) from exc


class AlertSession:
    """Uniform query interface over supported driver connections."""

    def __init__(
        self,
        backend: DatabaseBackend,
        connection: Any,
    ):
        self.backend = backend
        self.connection = connection
        self.dialect = dialect_for_backend(backend)
        self._cursors: list[Any] = []

    def execute(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        """Execute SQL and return a cursor-like result."""

        if self.backend.name == "mysql":
            cursor = self.connection.cursor(
                dictionary=True
            )
            cursor.execute(sql, tuple(parameters))
            self._cursors.append(cursor)
            return cursor

        return self.connection.execute(
            sql,
            tuple(parameters),
        )

    def close(self) -> None:
        """Close driver cursors owned by this session."""

        for cursor in reversed(self._cursors):
            cursor.close()

        self._cursors.clear()


class AlertRepository:
    """Backend-independent persistence entry point for alerts."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self) -> Mapping[str, Any]:
        return self.backend.initialize()

    @contextmanager
    def session(self) -> Iterator[AlertSession]:
        with self.backend.connect() as connection:
            session = AlertSession(
                self.backend,
                connection,
            )

            try:
                yield session
            finally:
                session.close()

    @contextmanager
    def transaction(self) -> Iterator[AlertSession]:
        with self.backend.transaction() as connection:
            session = AlertSession(
                self.backend,
                connection,
            )

            try:
                yield session
            finally:
                session.close()

    def get_alert(
        self,
        alert_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()

        with self.session() as session:
            row = session.execute(
                "SELECT * FROM alerts "
                f"WHERE id={self.dialect.placeholder}",
                (alert_id,),
            ).fetchone()

        return None if row is None else dict(row)

    def alert_history(
        self,
        alert_id: str,
    ) -> list[dict[str, Any]]:
        self.initialize()

        with self.session() as session:
            rows = session.execute(
                "SELECT * FROM alert_events "
                f"WHERE alert_id={self.dialect.placeholder} "
                "ORDER BY id",
                (alert_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    @staticmethod
    def suppression_deadline(minutes: int) -> datetime:
        """Return a portable UTC suppression timestamp."""

        if minutes <= 0:
            raise ValueError(
                "suppression minutes must be greater than zero"
            )

        return datetime.now(timezone.utc) + timedelta(
            minutes=minutes
        )

    def close(self) -> None:
        self.backend.close()
