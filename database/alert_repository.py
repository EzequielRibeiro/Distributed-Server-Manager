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

    def _filters(self, **values: Any) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in values.items():
            if value is not None:
                clauses.append(
                    f"{column}={self.dialect.placeholder}"
                )
                parameters.append(value)
        return clauses, parameters

    def list_alerts(
        self,
        *,
        active_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        self.initialize()
        clauses, parameters = self._filters(**filters)
        if active_only:
            clauses.insert(0, "state IN ('OPEN', 'ACKNOWLEDGED')")
        sql = "SELECT * FROM alerts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if active_only:
            sql += (
                " ORDER BY CASE level WHEN 'CRITICAL' THEN 0 "
                "WHEN 'WARNING' THEN 1 ELSE 2 END, opened_at DESC, id"
            )
        else:
            sql += " ORDER BY opened_at DESC, id"
        pagination, page_parameters = self.dialect.pagination(
            limit=limit,
            offset=offset,
        )
        with self.session() as session:
            rows = session.execute(
                sql + pagination,
                (*parameters, *page_parameters),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_alerts(
        self,
        *,
        active_only: bool = False,
        **filters: Any,
    ) -> int:
        self.initialize()
        clauses, parameters = self._filters(**filters)
        if active_only:
            clauses.insert(0, "state IN ('OPEN', 'ACKNOWLEDGED')")
        sql = "SELECT COUNT(*) AS total FROM alerts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self.session() as session:
            row = session.execute(sql, parameters).fetchone()
        return int(row["total"])

    def _event(
        self,
        session: AlertSession,
        alert_id: str,
        action: str,
        level: str,
        old_state: str | None,
        new_state: str,
        message: str,
    ) -> None:
        placeholders = self.dialect.parameters(6)
        session.execute(
            "INSERT INTO alert_events(alert_id, action, level, "
            "old_state, new_state, message) "
            f"VALUES ({placeholders})",
            (alert_id, action, level, old_state, new_state, message),
        )

    @staticmethod
    def _operator_message(value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) > 4000:
            raise ValueError("alert note must not exceed 4000 characters")
        return text

    def open_alert(
        self,
        *,
        alert_id: str,
        rule_id: str,
        level: str,
        message: str,
        scope: str,
        controller_id: str,
        agent_id: str | None = None,
        node_id: str | None = None,
        instance_id: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        with self.transaction() as session:
            current = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}",
                (alert_id,),
            ).fetchone()
            if current is None:
                columns = (
                    "id, scope, controller_id, agent_id, node_id, "
                    "instance_id, rule_id, level, state, message"
                )
                session.execute(
                    f"INSERT INTO alerts({columns}) VALUES "
                    f"({self.dialect.parameters(10)})",
                    (alert_id, scope, controller_id, agent_id, node_id,
                     instance_id, rule_id, level, "OPEN", message),
                )
                self._event(session, alert_id, "OPEN", level, None,
                            "OPEN", message)
                action = "OPEN"
            elif current["state"] in {"RESOLVED", "SUPPRESSED"}:
                old_state = current["state"]
                session.execute(
                    "UPDATE alerts SET "
                    f"scope={ph}, controller_id={ph}, agent_id={ph}, "
                    f"node_id={ph}, instance_id={ph}, rule_id={ph}, "
                    f"level={ph}, state='OPEN', message={ph}, "
                    f"opened_at={now}, updated_at={now}, "
                    "acknowledged_at=NULL, resolved_at=NULL, "
                    f"suppressed_until=NULL WHERE id={ph}",
                    (scope, controller_id, agent_id, node_id, instance_id,
                     rule_id, level, message, alert_id),
                )
                self._event(session, alert_id, "REOPEN", level, old_state,
                            "OPEN", message)
                action = "REOPEN"
            elif level == "CRITICAL" and current["level"] != "CRITICAL":
                old_state = current["state"]
                session.execute(
                    "UPDATE alerts SET level='CRITICAL', state='OPEN', "
                    f"message={ph}, updated_at={now}, "
                    f"acknowledged_at=NULL WHERE id={ph}",
                    (message, alert_id),
                )
                self._event(session, alert_id, "ESCALATE", "CRITICAL",
                            old_state, "OPEN", message)
                action = "ESCALATE"
            else:
                action = "UNCHANGED"
            row = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}",
                (alert_id,),
            ).fetchone()
        result = dict(row)
        result["action"] = action
        return result

    def _transition(
        self,
        alert_id: str,
        *,
        state: str,
        action: str,
        timestamp_column: str,
        missing_is_none: bool = False,
        event_message: str | None = None,
    ) -> dict[str, Any] | None:
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        operator_message = self._operator_message(event_message)
        with self.transaction() as session:
            current = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
            if current is None:
                if missing_is_none:
                    return None
                raise ValueError("alert not found")
            if current["state"] == state:
                return dict(current)
            if state == "ACKNOWLEDGED" and current["state"] != "OPEN":
                raise ValueError("only OPEN alerts can be acknowledged")
            extra = ", suppressed_until=NULL" if state == "RESOLVED" else ""
            session.execute(
                f"UPDATE alerts SET state={ph}, {timestamp_column}={now}, "
                f"updated_at={now}{extra} WHERE id={ph}",
                (state, alert_id),
            )
            self._event(
                session,
                alert_id,
                action,
                current["level"],
                current["state"],
                state,
                operator_message or current["message"],
            )
            row = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
        return dict(row)

    def acknowledge_alert(self, alert_id: str) -> dict[str, Any]:
        return self._transition(
            alert_id, state="ACKNOWLEDGED", action="ACK",
            timestamp_column="acknowledged_at",
        )

    def resolve_alert(
        self,
        alert_id: str,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        return self._transition(
            alert_id,
            state="RESOLVED",
            action="RESOLVE",
            timestamp_column="resolved_at",
            missing_is_none=True,
            event_message=note,
        )

    def note_alert(
        self,
        alert_id: str,
        note: str,
    ) -> dict[str, Any]:
        message = self._operator_message(note)
        if message is None:
            raise ValueError("alert note is required")
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        with self.transaction() as session:
            current = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
            if current is None:
                raise ValueError("alert not found")
            session.execute(
                f"UPDATE alerts SET updated_at={now} WHERE id={ph}",
                (alert_id,),
            )
            self._event(
                session,
                alert_id,
                "NOTE",
                current["level"],
                current["state"],
                current["state"],
                message,
            )
            row = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
        return dict(row)

    def reopen_alert(
        self,
        alert_id: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        message = self._operator_message(note)
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        with self.transaction() as session:
            current = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
            if current is None:
                raise ValueError("alert not found")
            if current["state"] not in {"RESOLVED", "SUPPRESSED"}:
                raise ValueError("only RESOLVED or SUPPRESSED alerts can be reopened")
            old_state = current["state"]
            session.execute(
                "UPDATE alerts SET state='OPEN', "
                f"opened_at={now}, updated_at={now}, "
                "acknowledged_at=NULL, resolved_at=NULL, "
                f"suppressed_until=NULL WHERE id={ph}",
                (alert_id,),
            )
            self._event(
                session,
                alert_id,
                "REOPEN",
                current["level"],
                old_state,
                "OPEN",
                message or current["message"],
            )
            row = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
        return dict(row)

    def suppress_alert(
        self,
        alert_id: str,
        minutes: int,
    ) -> dict[str, Any]:
        deadline = self.suppression_deadline(minutes)
        if self.backend.name == "sqlite":
            deadline = deadline.isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        with self.transaction() as session:
            current = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
            if current is None:
                raise ValueError("alert not found")
            session.execute(
                "UPDATE alerts SET state='SUPPRESSED', "
                f"suppressed_until={ph}, updated_at={now} WHERE id={ph}",
                (deadline, alert_id),
            )
            self._event(session, alert_id, "SUPPRESS", current["level"],
                        current["state"], "SUPPRESSED", current["message"])
            row = session.execute(
                f"SELECT * FROM alerts WHERE id={ph}", (alert_id,)
            ).fetchone()
        return dict(row)

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
