#!/usr/bin/env python3
"""Persistent Agent lifecycle transitions.

This repository is intentionally small: it reads the current Agent state inside
one database transaction, validates the requested change with the pure domain
state machine, and only then updates the row.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.agent_lifecycle import AgentTransition, transition_agent
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class AgentNotFound(LookupError):
    """Raised when a requested Agent does not exist."""


class AgentLifecycleRepository:
    """Apply validated Agent lifecycle transitions transactionally."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def transition(
        self,
        agent_id: str,
        target_state: str,
    ) -> AgentTransition:
        """Validate and persist one Agent state transition.

        The current state is read and the possible update is performed in the
        same backend transaction. Idempotent transitions return successfully
        without issuing an UPDATE.
        """
        ph = self.dialect.placeholder

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT status FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone()

                if row is None:
                    raise AgentNotFound(f"Agent not found: {agent_id}")

                result = transition_agent(
                    str(row["status"]),
                    target_state,
                )

                if result.changed:
                    session.execute(
                        f"UPDATE agents SET status={ph} WHERE id={ph}",
                        (result.target, agent_id),
                    )

                return result
            finally:
                session.close()

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
