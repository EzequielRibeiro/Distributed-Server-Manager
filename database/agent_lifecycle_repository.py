#!/usr/bin/env python3
"""Persistent Agent lifecycle transitions.

This repository is intentionally small: it reads the current Agent state inside
one database transaction, validates the requested change with the pure domain
state machine, and only then updates the row.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_lifecycle import AgentTransition, transition_agent
from core.events import EventPublisher, EventScope, EventSeverity, EventSource


class AgentNotFound(LookupError):
    """Raised when a requested Agent does not exist."""


LIFECYCLE_EVENTS: dict[str, tuple[str, EventSeverity]] = {
    "pairing": ("AGENT_PAIRING_STARTED", EventSeverity.INFO),
    "active": ("AGENT_ONLINE", EventSeverity.INFO),
    "offline": ("AGENT_OFFLINE", EventSeverity.WARNING),
    "disabled": ("AGENT_DISABLED", EventSeverity.NOTICE),
    "rejected": ("AGENT_REJECTED", EventSeverity.WARNING),
}


class AgentLifecycleRepository:
    """Apply validated Agent lifecycle transitions transactionally."""

    def __init__(
        self,
        backend: DatabaseBackend,
        *,
        event_publisher: EventPublisher | None = None,
    ):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.event_publisher = event_publisher

    def transition(
        self,
        agent_id: str,
        target_state: str,
    ) -> AgentTransition:
        """Validate and persist one Agent state transition.

        The current state is read and the possible update is performed in the
        same backend transaction. Idempotent transitions return successfully
        without issuing an UPDATE or publishing a duplicate event.
        """
        ph = self.dialect.placeholder
        controller_id: str | None = None

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT status, controller_id FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone()

                if row is None:
                    raise AgentNotFound(f"Agent not found: {agent_id}")

                result = transition_agent(
                    str(row["status"]),
                    target_state,
                )
                controller_id = str(row["controller_id"] or "").strip() or None

                if result.changed:
                    session.execute(
                        f"UPDATE agents SET status={ph} WHERE id={ph}",
                        (result.target, agent_id),
                    )
            finally:
                session.close()

        if result.changed:
            self._publish_transition(
                agent_id=agent_id,
                controller_id=controller_id,
                result=result,
            )

        return result

    def _publish_transition(
        self,
        *,
        agent_id: str,
        controller_id: str | None,
        result: AgentTransition,
    ) -> None:
        if self.event_publisher is None:
            return

        definition = LIFECYCLE_EVENTS.get(result.target)
        if definition is None:
            return

        event_type, severity = definition
        self.event_publisher.publish(
            event_type,
            source=EventSource(type="agent", id=agent_id),
            severity=severity,
            scope=EventScope(
                controller_id=controller_id,
                agent_id=agent_id,
            ),
            data={
                "previous_status": result.current,
                "status": result.target,
            },
        )

    def status(self, agent_id: str) -> str | None:
        """Return the persisted Agent state without changing it."""
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT status FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone()
            finally:
                session.close()

        if row is None:
            return None
        return str(row["status"])
