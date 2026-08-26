#!/usr/bin/env python3
"""Backend-neutral durable notification outbox persistence."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class NotificationOutboxRepository:
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

    def enqueue(
        self,
        *,
        channel: str,
        recipient: str,
        message: str,
        subject: str | None = None,
        event_id: str | None = None,
        alert_id: str | None = None,
        next_attempt_at: str | None = None,
    ) -> str:
        self.initialize()
        channel = str(channel or "").strip().lower()
        recipient = str(recipient or "").strip()
        message = str(message or "").strip()
        if not channel or not recipient or not message:
            raise ValueError("channel, recipient and message are required")
        notification_id = str(uuid.uuid4())
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO notification_outbox("
                "notification_id,event_id,alert_id,channel,recipient,subject,message,status,attempts,next_attempt_at"
                f") VALUES ({self.dialect.parameters(10)})",
                (
                    notification_id,
                    event_id,
                    alert_id,
                    channel,
                    recipient,
                    subject,
                    message,
                    "pending",
                    0,
                    next_attempt_at,
                ),
            )
        return notification_id

    def pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        bounded = max(1, min(int(limit or 100), 1000))
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT * FROM notification_outbox WHERE status='pending' "
                f"AND (next_attempt_at IS NULL OR next_attempt_at<=CURRENT_TIMESTAMP) "
                f"ORDER BY created_at,notification_id LIMIT {ph}",
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_processing(self, notification_id: str) -> None:
        self._set_status(notification_id, "processing", increment_attempts=True)

    def mark_delivered(self, notification_id: str) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE notification_outbox SET status='delivered',delivered_at=CURRENT_TIMESTAMP,"
                f"last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE notification_id={ph}",
                (notification_id,),
            )

    def mark_failed(self, notification_id: str, error: str, *, next_attempt_at: str | None = None) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE notification_outbox SET status='pending',last_error=" + ph +
                ",next_attempt_at=" + ph + ",updated_at=CURRENT_TIMESTAMP WHERE notification_id=" + ph,
                (str(error or "")[:4000], next_attempt_at, notification_id),
            )

    def cancel(self, notification_id: str) -> None:
        self._set_status(notification_id, "cancelled")

    def _set_status(self, notification_id: str, status: str, *, increment_attempts: bool = False) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        attempts = ",attempts=attempts+1" if increment_attempts else ""
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE notification_outbox SET status={ph}{attempts},updated_at=CURRENT_TIMESTAMP "
                f"WHERE notification_id={ph}",
                (status, notification_id),
            )


__all__ = ["NotificationOutboxRepository"]
