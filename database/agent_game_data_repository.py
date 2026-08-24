#!/usr/bin/env python3
"""Persistence and delivery coordination for Agent-owned game-data jobs."""
from __future__ import annotations
from contextlib import contextmanager
import json
from typing import Any, Iterator
import uuid
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp

FINAL_STATES = {"completed", "failed"}
FILE_ACTIONS = {"file-list", "file-read", "file-write", "file-create", "file-mkdir", "file-rename", "file-delete", "file-upload"}
VALID_ACTIONS = {"install", "update", "verify", "repair", "install-steamcmd", *FILE_ACTIONS}
VALID_STATES = {"queued", "delivered", "running", *FINAL_STATES}


def _logical_action(selection: Any, stored_action: str) -> str:
    if isinstance(selection, dict):
        value = str(selection.get("_job_action") or "").strip().lower()
        if value in {*FILE_ACTIONS, "repair", "install-steamcmd"}:
            return value
    return stored_action


def _redacted_selection(selection: Any) -> Any:
    if not isinstance(selection, dict):
        return selection
    value = dict(selection)
    operation = value.get("_file_operation")
    if isinstance(operation, dict):
        operation = dict(operation)
        operation.pop("content", None)
        operation.pop("content_base64", None)
        value["_file_operation"] = operation
    return value


class AgentGameDataRepository:
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

    def _agent_status(self, session: AlertSession, agent_id: str) -> str | None:
        ph = self.dialect.placeholder
        row = session.execute(f"SELECT status FROM agents WHERE id={ph}", (agent_id,)).fetchone()
        return None if row is None else str(row["status"] or "").strip().lower()

    def enqueue(self, *, agent_id: str, action: str, environment_id: str, selector: str, selection: dict[str, Any], requested_by: str | None = None) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        action = str(action or "").strip().lower()
        environment_id = str(environment_id or "").strip()
        selector = str(selector or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if action not in VALID_ACTIONS:
            raise ValueError("invalid game-data action")
        if not environment_id:
            raise ValueError("environment_id is required")
        if not selector:
            raise ValueError("selector is required")
        if not isinstance(selection, dict) or not selection:
            raise ValueError("runtime selection is required")

        stored_selection = dict(selection)
        # The consolidated schemas intentionally constrain the persisted transport
        # action to install/update/verify. Preserve compatibility with deployed
        # databases by retaining newer logical actions in selection metadata.
        stored_action = action
        if action in FILE_ACTIONS:
            stored_action = "verify"
            stored_selection["_job_action"] = action
        elif action in {"repair", "install-steamcmd"}:
            stored_action = "update"
            stored_selection["_job_action"] = action

        job_id = "game-data-" + uuid.uuid4().hex
        now = utc_timestamp()
        payload = json.dumps(stored_selection, separators=(",", ":"), sort_keys=True)
        with self.session(transaction=True) as session:
            status = self._agent_status(session, agent_id)
            if status is None:
                raise ValueError("Agent not found")
            if status != "active":
                raise ValueError("Agent must be active")
            session.execute(
                "INSERT INTO agent_game_data_jobs(job_id,agent_id,action,environment_id,selector,selection_json,status,progress,requested_by,created_at,updated_at) "
                f"VALUES ({self.dialect.parameters(11)})",
                (job_id, agent_id, stored_action, environment_id, selector, payload, "queued", 0, str(requested_by or "").strip() or None, now, now),
            )
        return self.snapshot(job_id)

    def snapshot(self, job_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT * FROM agent_game_data_jobs WHERE job_id={ph}", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        stored_action = str(result.get("action") or "").strip().lower()
        for key in ("selection_json", "result_json"):
            raw = result.pop(key, None)
            target = "selection" if key == "selection_json" else "result"
            try:
                result[target] = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                result[target] = None
        logical_action = _logical_action(result.get("selection"), stored_action)
        if logical_action != stored_action:
            result["transport_action"] = stored_action
            result["action"] = logical_action
        return result

    def list_for_agent(self, agent_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT job_id FROM agent_game_data_jobs "
                f"WHERE agent_id={ph} ORDER BY created_at DESC LIMIT {limit}",
                (agent_id,),
            ).fetchall()
        return [self.snapshot(str(row["job_id"])) for row in rows]

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT job_id FROM agent_game_data_jobs "
                f"WHERE agent_id={ph} AND status IN ('queued','delivered','running') ORDER BY created_at ASC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        state = self.snapshot(str(row["job_id"]))
        command = {key: state[key] for key in ("job_id", "agent_id", "action", "environment_id", "selector", "selection")}
        selection = command.get("selection") if isinstance(command.get("selection"), dict) else {}
        if isinstance(selection.get("_file_operation"), dict):
            command["file_operation"] = dict(selection["_file_operation"])
        return command

    def mark_delivered(self, job_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        now = utc_timestamp()
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_game_data_jobs SET "
                "status=CASE WHEN status='queued' THEN 'delivered' ELSE status END,"
                f"delivered_at=CASE WHEN delivered_at IS NULL THEN {ph} ELSE delivered_at END,"
                f"updated_at={ph} WHERE job_id={ph} AND status IN ('queued','delivered','running')",
                (now, now, job_id),
            )
        return self.snapshot(job_id)

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        job_id = str(result.get("job_id") or "").strip()
        if not job_id:
            return None
        current = self.snapshot(job_id)
        if str(current.get("agent_id")) != str(agent_id):
            raise PermissionError("game-data job belongs to another Agent")
        status = str(result.get("status") or "").strip().lower()
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid game-data result status")
        try:
            progress = int(result.get("progress", 100 if status == "completed" else current.get("progress", 0)))
        except (TypeError, ValueError):
            progress = int(current.get("progress", 0) or 0)
        progress = 100 if status == "completed" else max(0, min(progress, 100))
        now = utc_timestamp()
        error = str(result.get("error") or "").strip()[:2000] or None
        result_json = json.dumps(result, separators=(",", ":"), sort_keys=True)
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            if status == "running":
                session.execute(
                    "UPDATE agent_game_data_jobs SET "
                    f"status={ph},progress={ph},started_at=CASE WHEN started_at IS NULL THEN {ph} ELSE started_at END,"
                    f"result_json={ph},last_error={ph},updated_at={ph} WHERE job_id={ph} AND status NOT IN ('completed','failed')",
                    (status, progress, now, result_json, error, now, job_id),
                )
            else:
                selection_json = json.dumps(_redacted_selection(current.get("selection")), separators=(",", ":"), sort_keys=True)
                session.execute(
                    "UPDATE agent_game_data_jobs SET "
                    f"status={ph},progress={ph},selection_json={ph},result_json={ph},last_error={ph},completed_at={ph},updated_at={ph} "
                    f"WHERE job_id={ph} AND status NOT IN ('completed','failed')",
                    (status, progress, selection_json, result_json, error, now, now, job_id),
                )
        return self.snapshot(job_id)


__all__ = ["AgentGameDataRepository", "FILE_ACTIONS", "FINAL_STATES", "VALID_ACTIONS", "VALID_STATES"]
