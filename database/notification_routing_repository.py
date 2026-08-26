#!/usr/bin/env python3
"""Database-backed notification destination and routing persistence."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from notification_outbox_repository import NotificationOutboxRepository

_SEVERITY_RANK = {"info": 10, "warning": 20, "critical": 30}


class NotificationRoutingRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.outbox = NotificationOutboxRepository(backend)

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

    def create_destination(
        self,
        *,
        name: str,
        channel: str,
        recipient: str,
        secret_file: str | None = None,
        config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> str:
        self.initialize()
        name = str(name or "").strip()
        channel = str(channel or "").strip().lower()
        recipient = str(recipient or "").strip()
        secret_file = str(secret_file or "").strip() or None
        if not name or not channel or not recipient:
            raise ValueError("name, channel and recipient are required")
        destination_id = str(uuid.uuid4())
        config_json = json.dumps(config or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO notification_destinations("
                "destination_id,name,channel,recipient,secret_file,config_json,enabled"
                f") VALUES ({self.dialect.parameters(7)})",
                (destination_id, name, channel, recipient, secret_file, config_json, 1 if enabled else 0),
            )
        return destination_id

    def set_destination_enabled(self, destination_id: str, enabled: bool) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE notification_destinations SET enabled={ph},updated_at=CURRENT_TIMESTAMP "
                f"WHERE destination_id={ph}",
                (1 if enabled else 0, destination_id),
            )

    def list_destinations(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        self.initialize()
        sql = "SELECT * FROM notification_destinations"
        params: tuple[Any, ...] = ()
        if enabled_only:
            sql += f" WHERE enabled={self.dialect.placeholder}"
            params = (1,)
        sql += " ORDER BY name,destination_id"
        with self.session() as session:
            rows = session.execute(sql, params).fetchall()
        return [self._destination_row(row) for row in rows]

    def create_route(
        self,
        *,
        destination_id: str,
        event_type: str | None = None,
        minimum_severity: str = "warning",
        enabled: bool = True,
    ) -> str:
        self.initialize()
        event_type = str(event_type or "").strip().upper() or None
        minimum_severity = str(minimum_severity or "").strip().lower()
        if minimum_severity not in _SEVERITY_RANK:
            raise ValueError("minimum_severity must be info, warning or critical")
        route_id = str(uuid.uuid4())
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO notification_routes("
                "route_id,destination_id,event_type,minimum_severity,enabled"
                f") VALUES ({self.dialect.parameters(5)})",
                (route_id, destination_id, event_type, minimum_severity, 1 if enabled else 0),
            )
        return route_id

    def set_route_enabled(self, route_id: str, enabled: bool) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE notification_routes SET enabled={ph},updated_at=CURRENT_TIMESTAMP "
                f"WHERE route_id={ph}",
                (1 if enabled else 0, route_id),
            )

    def matching_destinations(self, *, event_type: str, severity: str) -> list[dict[str, Any]]:
        self.initialize()
        event_type = str(event_type or "").strip().upper()
        severity = str(severity or "").strip().lower()
        if severity not in _SEVERITY_RANK:
            raise ValueError("severity must be info, warning or critical")
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT r.route_id,r.event_type,r.minimum_severity,d.* "
                "FROM notification_routes r JOIN notification_destinations d "
                "ON d.destination_id=r.destination_id "
                f"WHERE r.enabled={ph} AND d.enabled={ph} AND (r.event_type IS NULL OR r.event_type={ph}) "
                "ORDER BY d.name,r.route_id",
                (1, 1, event_type),
            ).fetchall()
        current_rank = _SEVERITY_RANK[severity]
        result = []
        seen: set[str] = set()
        for row in rows:
            item = dict(row)
            minimum = str(item.get("minimum_severity") or "warning").lower()
            if current_rank < _SEVERITY_RANK.get(minimum, 999):
                continue
            destination_id = str(item.get("destination_id") or "")
            if destination_id in seen:
                continue
            seen.add(destination_id)
            item.update(self._destination_row(item))
            result.append(item)
        return result

    def enqueue_event(
        self,
        *,
        event_id: str,
        event_type: str,
        severity: str,
        message: str,
        subject: str | None = None,
        alert_id: str | None = None,
    ) -> list[str]:
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")
        notification_ids = []
        for destination in self.matching_destinations(event_type=event_type, severity=severity):
            notification_ids.append(self.outbox.enqueue(
                channel=str(destination["channel"]),
                recipient=str(destination["recipient"]),
                message=message,
                subject=subject,
                event_id=event_id,
                alert_id=alert_id,
            ))
        return notification_ids

    @staticmethod
    def _destination_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        try:
            item["config"] = json.loads(item.pop("config_json", "{}") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            item["config"] = {}
        item["enabled"] = bool(item.get("enabled"))
        return item


__all__ = ["NotificationRoutingRepository"]
