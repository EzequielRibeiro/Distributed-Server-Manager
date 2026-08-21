#!/usr/bin/env python3
"""Backend-independent persistence for Universal Event Platform events."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = Path(__file__).resolve().parent
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseBackend, DatabaseConfigurationError
from core.events.models import EventScope, EventSeverity, EventSource, UniversalEvent
from core.events.validator import validate_event


PLACEHOLDERS = {
    "sqlite": "?",
    "postgresql": "%s",
    "mysql": "%s",
}


class EventRepository:
    """Persist and retrieve immutable universal events."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        try:
            self.placeholder = PLACEHOLDERS[backend.name]
        except KeyError as exc:
            raise DatabaseConfigurationError(
                f"unsupported event repository backend: {backend.name}"
            ) from exc

    def _execute(
        self,
        connection: Any,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        if self.backend.name == "mysql":
            cursor = connection.cursor(dictionary=True)
            cursor.execute(sql, tuple(parameters))
            return cursor
        return connection.execute(sql, tuple(parameters))

    def store(self, event: UniversalEvent) -> None:
        """Persist one validated event atomically."""

        validate_event(event)
        self.backend.initialize()
        payload = event.to_dict()
        scope = event.scope
        timestamp = payload["timestamp"]
        source_compat = f"{event.source.type}:{event.source.id}"

        columns = (
            "event_id, event_type, event_version, occurred_at, severity, "
            "source, source_type, source_id, controller_id, agent_id, "
            "customer_id, instance_id, correlation_id, causation_id, "
            "payload_json"
        )
        placeholders = ",".join(self.placeholder for _ in range(15))
        values = (
            event.id,
            event.type,
            event.version,
            timestamp,
            event.severity.value,
            source_compat,
            event.source.type,
            event.source.id,
            scope.controller_id,
            scope.agent_id,
            scope.customer_id,
            scope.instance_id,
            event.correlation_id,
            event.causation_id,
            json.dumps(event.data, separators=(",", ":"), sort_keys=True),
        )

        with self.backend.transaction() as connection:
            cursor = self._execute(
                connection,
                f"INSERT INTO events({columns}) VALUES ({placeholders})",
                values,
            )
            if self.backend.name == "mysql":
                cursor.close()

    def get(self, event_id: str) -> UniversalEvent | None:
        """Return one universal event by immutable event ID."""

        self.backend.initialize()
        with self.backend.connect() as connection:
            cursor = self._execute(
                connection,
                "SELECT event_id, event_type, event_version, occurred_at, "
                "severity, source_type, source_id, controller_id, agent_id, "
                "customer_id, instance_id, correlation_id, causation_id, "
                f"payload_json FROM events WHERE event_id={self.placeholder}",
                (event_id,),
            )
            row = cursor.fetchone()
            if self.backend.name == "mysql":
                cursor.close()

        if row is None:
            return None

        record = dict(row)
        if not record.get("source_type") or not record.get("source_id"):
            raise ValueError(
                f"event {event_id} predates the universal event contract"
            )
        if not record.get("occurred_at"):
            raise ValueError(
                f"event {event_id} has no universal occurrence timestamp"
            )

        timestamp = str(record["occurred_at"])
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"

        event = UniversalEvent(
            id=str(record["event_id"]),
            type=str(record["event_type"]),
            version=int(record["event_version"]),
            timestamp=datetime.fromisoformat(timestamp),
            severity=EventSeverity(str(record["severity"])),
            source=EventSource(
                type=str(record["source_type"]),
                id=str(record["source_id"]),
            ),
            scope=EventScope(
                controller_id=record.get("controller_id"),
                agent_id=record.get("agent_id"),
                customer_id=record.get("customer_id"),
                instance_id=record.get("instance_id"),
            ),
            correlation_id=record.get("correlation_id"),
            causation_id=record.get("causation_id"),
            data=json.loads(record["payload_json"] or "{}"),
        )
        validate_event(event)
        return event

    def close(self) -> None:
        self.backend.close()
