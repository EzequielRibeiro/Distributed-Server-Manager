#!/usr/bin/env python3
"""Controller-side queue for game-agnostic Agent instance operations."""

from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp

VALID_ACTIONS = {"status", "doctor", "start", "stop", "restart", "remove"}
LIFECYCLE_ACTIONS = {"start", "stop", "restart"}
ACTIVE_STATES = {"queued", "delivered"}
FINAL_STATES = {"completed", "failed"}


class InstanceLifecycleCommandConflict(RuntimeError):
    """A different lifecycle command is already active for an instance."""

    def __init__(
        self,
        *,
        instance_id: str,
        requested_action: str,
        active_action: str,
        command_id: str,
    ):
        self.instance_id = str(instance_id)
        self.requested_action = str(requested_action)
        self.active_action = str(active_action)
        self.command_id = str(command_id)
        super().__init__(
            f"Instance {self.instance_id} already has active lifecycle command "
            f"{self.active_action} ({self.command_id})"
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "error": "lifecycle_operation_in_progress",
            "message": str(self),
            "instance_id": self.instance_id,
            "requested_action": self.requested_action,
            "active_action": self.active_action,
            "command_id": self.command_id,
        }


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
        existing_command_id: str | None = None
        with self.session(transaction=True) as session:
            agent = session.execute(f"SELECT status FROM agents WHERE id={ph}", (agent_id,)).fetchone()
            if agent is None or str(agent["status"] or "").lower() != "active":
                raise ValueError("Agent must be active")

            # Lifecycle arbitration is serialized on the authoritative instance
            # row. PostgreSQL/MySQL use a row-level lock; SQLite transactions are
            # opened with BEGIN IMMEDIATE by SQLiteBackend, which serializes the
            # check-and-insert sequence without unsupported FOR UPDATE syntax.
            instance_query = f"SELECT agent_id FROM instances WHERE id={ph}"
            if str(getattr(self.backend, "name", "")).strip().lower() != "sqlite":
                instance_query += " FOR UPDATE"
            instance = session.execute(instance_query, (instance_id,)).fetchone()
            if instance is None:
                raise ValueError("Instance not found")
            if str(instance["agent_id"] or "") != agent_id:
                raise PermissionError("Instance belongs to another Agent")

            if action in LIFECYCLE_ACTIONS:
                existing = session.execute(
                    "SELECT command_id,action FROM agent_instance_commands "
                    f"WHERE instance_id={ph} AND action IN ('start','stop','restart') "
                    "AND status IN ('queued','delivered') "
                    "ORDER BY created_at ASC LIMIT 1",
                    (instance_id,),
                ).fetchone()
                if existing is not None:
                    command_id = str(existing["command_id"])
                    active_action = str(existing["action"] or "").strip().lower()
                    if active_action == action:
                        existing_command_id = command_id
                    else:
                        raise InstanceLifecycleCommandConflict(
                            instance_id=instance_id,
                            requested_action=action,
                            active_action=active_action,
                            command_id=command_id,
                        )

            if action == "remove" and existing_command_id is None:
                existing = session.execute(
                    "SELECT command_id FROM agent_instance_commands "
                    f"WHERE instance_id={ph} AND action={ph} AND status IN ('queued','delivered') "
                    "ORDER BY created_at ASC LIMIT 1",
                    (instance_id, action),
                ).fetchone()
                if existing is not None:
                    existing_command_id = str(existing["command_id"])

            if existing_command_id is None:
                command_id = "instance-cmd-" + uuid.uuid4().hex
                now = utc_timestamp()
                session.execute(
                    "INSERT INTO agent_instance_commands(command_id,agent_id,instance_id,action,status,requested_by,created_at,updated_at) "
                    f"VALUES ({self.dialect.parameters(8)})",
                    (command_id, agent_id, instance_id, action, "queued", str(requested_by or "").strip() or None, now, now),
                )
            else:
                command_id = existing_command_id
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

        reported_instance_id = str(result.get("instance_id") or "").strip()
        if reported_instance_id != str(current.get("instance_id") or ""):
            raise ValueError("instance command result instance_id mismatch")
        reported_action = str(result.get("action") or "").strip().lower()
        if reported_action != str(current.get("action") or "").strip().lower():
            raise ValueError("instance command result action mismatch")

        status = str(result.get("status") or "").strip().lower()
        if status not in FINAL_STATES:
            raise ValueError("invalid instance command result status")
        now = utc_timestamp()
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        error = str(result.get("error") or "").strip()[:2000] or None
        ph = self.dialect.placeholder

        contract_id = None
        if reported_action == "remove":
            with self.session() as session:
                link = session.execute(
                    f"SELECT contract_id FROM instance_contracts WHERE instance_id={ph}",
                    (reported_instance_id,),
                ).fetchone()
            if link is not None:
                contract_id = str(link["contract_id"])

        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_instance_commands SET "
                f"status={ph},result_json={ph},last_error={ph},completed_at={ph},updated_at={ph} "
                f"WHERE command_id={ph} AND status NOT IN ('completed','failed')",
                (status, payload, error, now, now, command_id),
            )
        completed = self.snapshot(command_id)

        if reported_action == "remove" and status == "completed":
            from admin_management_repository import AdminManagementRepository
            from dashboard_repository import DashboardRepository

            DashboardRepository(self.backend).delete_instance(reported_instance_id)
            AdminManagementRepository(self.backend).finalize_contract_if_empty(contract_id)

        return completed


__all__ = [
    "ACTIVE_STATES",
    "AgentInstanceRuntimeRepository",
    "FINAL_STATES",
    "InstanceLifecycleCommandConflict",
    "LIFECYCLE_ACTIONS",
    "VALID_ACTIONS",
]
