#!/usr/bin/env python3
"""Controller-side queue for Agent-owned instance file operations."""
from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend

VALID_ACTIONS = {
    "list", "usage", "read_text", "write_text", "download", "upload",
    "mkdir", "delete", "rename", "move", "extract",
}
FINAL_STATES = {"completed", "failed"}


class InstanceFileRepository:
    def __init__(self, backend):
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

    @staticmethod
    def _json(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _decode(value: Any, default=None):
        if value in {None, ""}:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except (TypeError, ValueError):
            return default

    def enqueue(
        self,
        *,
        agent_id: str,
        instance_id: str,
        action: str,
        requested_by: str,
        path: str | None = None,
        target_path: str | None = None,
        payload: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        instance_id = str(instance_id or "").strip()
        action = str(action or "").strip().lower()
        requested_by = str(requested_by or "").strip()
        if not agent_id or not instance_id or not requested_by:
            raise ValueError("agent_id, instance_id and requested_by are required")
        if action not in VALID_ACTIONS:
            raise ValueError("invalid instance file action")
        self.initialize(); ph = self.dialect.placeholder
        command_id = "instance-file-" + uuid.uuid4().hex
        with self.session(transaction=True) as session:
            instance = session.execute(
                f"SELECT agent_id FROM instances WHERE id={ph}", (instance_id,)
            ).fetchone()
            if instance is None:
                raise LookupError("instance not found")
            if str(instance["agent_id"] or "") != agent_id:
                raise PermissionError("instance belongs to another Agent")
            session.execute(
                "INSERT INTO instance_file_commands(command_id,agent_id,instance_id,action,path,target_path,payload_json,policy_json,status,requested_by) "
                f"VALUES ({self.dialect.parameters(10)})",
                (
                    command_id, agent_id, instance_id, action,
                    str(path or "").strip() or None,
                    str(target_path or "").strip() or None,
                    self._json(payload), self._json(policy), "queued", requested_by,
                ),
            )
        return self.snapshot(command_id)

    def snapshot(self, command_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT * FROM instance_file_commands WHERE command_id={ph}",
                (str(command_id),),
            ).fetchone()
        if row is None:
            raise KeyError(command_id)
        result = dict(row)
        result["payload"] = self._decode(result.pop("payload_json", None), {})
        result["policy"] = self._decode(result.pop("policy_json", None), {})
        result["result"] = self._decode(result.pop("result_json", None), None)
        return result

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            row = session.execute(
                "SELECT command_id FROM instance_file_commands "
                f"WHERE agent_id={ph} AND status='queued' ORDER BY created_at ASC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if row is None:
                return None
            command_id = str(row["command_id"])
            session.execute(
                f"UPDATE instance_file_commands SET status='delivered',delivered_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} "
                f"WHERE command_id={ph} AND status='queued'",
                (command_id,),
            )
        state = self.snapshot(command_id)
        return {
            "command_id": state["command_id"],
            "instance_id": state["instance_id"],
            "action": state["action"],
            "path": state.get("path"),
            "target_path": state.get("target_path"),
            "payload": state.get("payload") or {},
            "policy": state.get("policy") or {},
        }

    def apply_result(self, agent_id: str, report: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(report, dict):
            return None
        command_id = str(report.get("command_id") or "").strip()
        if not command_id:
            return None
        current = self.snapshot(command_id)
        if str(current.get("agent_id") or "") != str(agent_id or ""):
            raise PermissionError("file command belongs to another Agent")
        if str(report.get("instance_id") or "") != str(current.get("instance_id") or ""):
            raise ValueError("file command result instance mismatch")
        if str(report.get("action") or "") != str(current.get("action") or ""):
            raise ValueError("file command result action mismatch")
        status = str(report.get("status") or "").strip().lower()
        if status not in FINAL_STATES:
            raise ValueError("invalid file command result status")
        result_json = self._json(report.get("result"))
        error = str(report.get("error") or "").strip()[:4000] or None
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE instance_file_commands SET status={ph},result_json={ph},last_error={ph},completed_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} "
                f"WHERE command_id={ph} AND status IN ('queued','delivered')",
                (status, result_json, error, command_id),
            )
        return self.snapshot(command_id)


__all__ = ["FINAL_STATES", "InstanceFileRepository", "VALID_ACTIONS"]
