#!/usr/bin/env python3
"""Controller-side projection of final Agent instance runtime health."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp


class AgentInstanceRuntimeHealthRepository:
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

    def apply_inventory(self, agent_id: str, values: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        agent_id = str(agent_id or "").strip()
        if not agent_id or not isinstance(values, list):
            return []
        ph = self.dialect.placeholder
        now = utc_timestamp()
        applied: list[dict[str, Any]] = []
        with self.session(transaction=True) as session:
            for raw in values[:1000]:
                if not isinstance(raw, dict):
                    continue
                instance_id = str(raw.get("instance_id") or "").strip()
                if not instance_id:
                    continue
                owner = session.execute(f"SELECT agent_id FROM instances WHERE id={ph}", (instance_id,)).fetchone()
                if owner is None or str(owner["agent_id"] or "") != agent_id:
                    continue
                row = (
                    agent_id,
                    str(raw.get("desired_state") or "")[:32] or None,
                    str(raw.get("observed_state") or "")[:32] or None,
                    str(raw.get("reconcile_status") or "unknown")[:32],
                    str(raw.get("health") or "unknown")[:32],
                    str(raw.get("operation_status") or "idle")[:32],
                    str(raw.get("operation") or "")[:64] or None,
                    str(raw.get("last_error") or "")[:2000] or None,
                    str(raw.get("last_transition_at") or "") or None,
                    str(raw.get("generated_at") or "") or None,
                    now,
                    instance_id,
                )
                updated = session.execute(
                    "UPDATE agent_instance_runtime_health SET "
                    f"agent_id={ph},desired_state={ph},observed_state={ph},reconcile_status={ph},health={ph},"
                    f"operation_status={ph},operation_name={ph},last_error={ph},last_transition_at={ph},reported_at={ph},updated_at={ph} "
                    f"WHERE instance_id={ph}", row,
                )
                if not getattr(updated, "rowcount", 0):
                    session.execute(
                        "INSERT INTO agent_instance_runtime_health("
                        "instance_id,agent_id,desired_state,observed_state,reconcile_status,health,operation_status,operation_name,last_error,last_transition_at,reported_at,updated_at) "
                        f"VALUES ({self.dialect.parameters(12)})",
                        (instance_id, *row[:-1]),
                    )
                applied.append({"instance_id": instance_id, "health": row[4], "operation_status": row[5]})
        return applied

    def list_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                f"SELECT * FROM agent_instance_runtime_health WHERE agent_id={ph} ORDER BY instance_id", (str(agent_id),)
            ).fetchall()
        return [dict(row) for row in rows]


__all__ = ["AgentInstanceRuntimeHealthRepository"]
