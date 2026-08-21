#!/usr/bin/env python3
"""Controller-side queue for game-agnostic Agent instance observations."""

from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp

VALID_ACTIONS = {"status", "doctor"}
FINAL_STATES = {"completed", "failed"}


class AgentInstanceRuntimeRepository:
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

    def enqueue(self, *, agent_id: str, instance_id: str, action: str, requested_by: str | None = None) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        instance_id = str(instance_id or "").strip()
        action = str(action or "").strip().lower()
        if not agent_id or not instance_id:
            raise ValueError("agent_id and instance_id are required")
        if action not in VALID_ACTIONS:
            raise ValueError("invalid instance runtime action")
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            agent = session.execute(f"SELECT status FROM agents WHERE id={ph}", (agent_id,)).fetchone()
            if agent is None or str(agent["status"] or "").lower() != "active":
                raise ValueError("Agent must be active")
            instance = session.execute(f"SELECT agent_id FROM instances WHERE id={ph}", (instance_id,)).fetchone()
            if instance is None:
                raise ValueError("Instance not found")
            if str(instance["agent_id"] or "") != agent_id:
                raise PermissionError("Instance belongs to another Agent")
            command_id = "instance-cmd-" + uuid.uuid4().hex
            now = utc_timestamp()
            session.execute(
                "INSERT INTO agent_instance_commands(command_id,agent_id,instance_id,action,status,requested_by,created_at,updated_at) "
                f"VALUES ({self.dialect.parameters(8)})",
                (command_id, agent_id, instance_id, action, "queued", str(requested_by or "").strip() or None, now, now),
            )
        return self.snapshot(command_id)

    def snapshot(self, command_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT * FROM agent_instance_commands WHERE command_id={ph}", (command_id,)).fetchone()
        if row is None:
            raise KeyError(command_id)
        result = dict(row)
        raw = result.pop("result_json", None)
        try:
            result["result"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            result["result"] = None
        return result

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT command_id FROM agent_instance_commands "
                f"WHERE agent_id={ph} AND status IN ('queued','delivered') ORDER BY created_at ASC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        state = self.snapshot(str(row["command_id"]))
        return {key: state[key] for key in ("command_id", "agent_id", "instance_id", "action")}

    def mark_delivered(self, command_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        now = utc_timestamp()
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_instance_commands SET "
                "status=CASE WHEN status='queued' THEN 'delivered' ELSE status END,"
                f"delivered_at=CASE WHEN delivered_at IS NULL THEN {ph} ELSE delivered_at END,updated_at={ph} "
                f"WHERE command_id={ph} AND status IN ('queued','delivered')",
                (now, now, command_id),
            )
        return self.snapshot(command_id)

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        command_id = str(result.get("command_id") or "").strip()
        if not command_id:
            return None
        current = self.snapshot(command_id)
        if str(current.get("agent_id")) != str(agent_id):
            raise PermissionError("instance command belongs to another Agent")
        status = str(result.get("status") or "").strip().lower()
        if status not in FINAL_STATES:
            raise ValueError("invalid instance command result status")
        now = utc_timestamp()
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        error = str(result.get("error") or "").strip()[:2000] or None
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_instance_commands SET "
                f"status={ph},result_json={ph},last_error={ph},completed_at={ph},updated_at={ph} "
                f"WHERE command_id={ph} AND status NOT IN ('completed','failed')",
                (status, payload, error, now, now, command_id),
            )
        return self.snapshot(command_id)


__all__ = ["AgentInstanceRuntimeRepository", "FINAL_STATES", "VALID_ACTIONS"]
