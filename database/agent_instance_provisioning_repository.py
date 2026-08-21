#!/usr/bin/env python3
"""Controller-side durable queue for Agent-owned instance service provisioning."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import PurePosixPath
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp

VALID_ACTIONS = {"provision", "reconcile", "remove"}
FINAL_STATES = {"completed", "failed"}


def normalize_runtime_contract(runtime: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(runtime, dict):
        raise ValueError("runtime contract is required")
    adapter = str(runtime.get("adapter") or "").strip().lower()
    if adapter != "systemd":
        raise ValueError("only the systemd instance adapter is supported")
    game_id = str(runtime.get("game_id") or "").strip()
    runtime_id = str(runtime.get("runtime_id") or "").strip()
    environment_id = str(runtime.get("environment_id") or runtime_id).strip()
    if not game_id or not runtime_id or not environment_id:
        raise ValueError("game_id, runtime_id and environment_id are required")
    launch = runtime.get("launch")
    if not isinstance(launch, dict):
        raise ValueError("runtime launch profile is required")
    executable = str(launch.get("executable") or "").strip()
    path = PurePosixPath(executable)
    if not executable or path.is_absolute() or ".." in path.parts or executable.startswith("./"):
        raise ValueError("launch executable must be a relative game-data path")
    arguments = launch.get("arguments", [])
    if not isinstance(arguments, list) or len(arguments) > 64:
        raise ValueError("launch arguments must contain at most 64 entries")
    clean_arguments: list[str] = []
    for item in arguments:
        value = str(item)
        if len(value) > 1024 or any(ch in value for ch in ("\x00", "\n", "\r", "$")):
            raise ValueError("invalid launch argument")
        clean_arguments.append(value)
    return {
        "adapter": "systemd",
        "game_id": game_id,
        "runtime_id": runtime_id,
        "environment_id": environment_id,
        "launch": {"executable": path.as_posix(), "arguments": clean_arguments},
    }


class AgentInstanceProvisioningRepository:
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
        agent_id: str,
        instance_id: str,
        action: str,
        runtime: dict[str, Any] | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        instance_id = str(instance_id or "").strip()
        action = str(action or "").strip().lower()
        if not agent_id or not instance_id:
            raise ValueError("agent_id and instance_id are required")
        if action not in VALID_ACTIONS:
            raise ValueError("invalid instance provisioning action")
        normalized_runtime = None if action == "remove" else normalize_runtime_contract(runtime)
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            agent = session.execute(f"SELECT status FROM agents WHERE id={ph}", (agent_id,)).fetchone()
            if agent is None or str(agent["status"] or "").lower() != "active":
                raise ValueError("Agent must be active")
            instance = session.execute(
                f"SELECT agent_id,game_id FROM instances WHERE id={ph}", (instance_id,)
            ).fetchone()
            if instance is None:
                raise ValueError("Instance not found")
            if str(instance["agent_id"] or "") != agent_id:
                raise PermissionError("Instance belongs to another Agent")
            if normalized_runtime and normalized_runtime["game_id"] != str(instance["game_id"] or ""):
                raise ValueError("runtime game_id does not match instance")
            pending = session.execute(
                "SELECT job_id FROM agent_instance_provisioning_jobs "
                f"WHERE instance_id={ph} AND status IN ('queued','delivered') ORDER BY created_at ASC LIMIT 1",
                (instance_id,),
            ).fetchone()
            if pending is not None:
                raise ValueError("Instance already has a pending provisioning job")
            job_id = "instance-provision-" + uuid.uuid4().hex
            request: dict[str, Any] = {
                "schema_version": 1,
                "kind": "CapivaraInstanceProvisioningRequest",
                "job_id": job_id,
                "agent_id": agent_id,
                "instance_id": instance_id,
                "action": action,
            }
            if normalized_runtime is not None:
                request["runtime"] = normalized_runtime
            now = utc_timestamp()
            session.execute(
                "INSERT INTO agent_instance_provisioning_jobs("
                "job_id,agent_id,instance_id,action,status,request_json,requested_by,created_at,updated_at"
                f") VALUES ({self.dialect.parameters(9)})",
                (
                    job_id, agent_id, instance_id, action, "queued",
                    json.dumps(request, separators=(",", ":"), sort_keys=True),
                    str(requested_by or "").strip() or None, now, now,
                ),
            )
        return self.snapshot(job_id)

    def snapshot(self, job_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT * FROM agent_instance_provisioning_jobs WHERE job_id={ph}", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        value = dict(row)
        for source, target in (("request_json", "request"), ("result_json", "result")):
            raw = value.pop(source, None)
            try:
                value[target] = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                value[target] = None
        return value

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT request_json FROM agent_instance_provisioning_jobs "
                f"WHERE agent_id={ph} AND status IN ('queued','delivered') ORDER BY created_at ASC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["request_json"] or "{}")
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def mark_delivered(self, job_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        now = utc_timestamp()
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_instance_provisioning_jobs SET "
                "status=CASE WHEN status='queued' THEN 'delivered' ELSE status END,"
                f"delivered_at=CASE WHEN delivered_at IS NULL THEN {ph} ELSE delivered_at END,updated_at={ph} "
                f"WHERE job_id={ph} AND status IN ('queued','delivered')",
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
        if str(current.get("agent_id") or "") != str(agent_id):
            raise PermissionError("provisioning job belongs to another Agent")
        if str(result.get("instance_id") or "") != str(current.get("instance_id") or ""):
            raise ValueError("provisioning result instance_id mismatch")
        if str(result.get("action") or "").lower() != str(current.get("action") or "").lower():
            raise ValueError("provisioning result action mismatch")
        status = str(result.get("status") or "").lower()
        if status not in FINAL_STATES:
            raise ValueError("invalid provisioning result status")
        now = utc_timestamp()
        ph = self.dialect.placeholder
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        error = str(result.get("error") or "").strip()[:2000] or None
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_instance_provisioning_jobs SET "
                f"status={ph},result_json={ph},last_error={ph},completed_at={ph},updated_at={ph} "
                f"WHERE job_id={ph} AND status NOT IN ('completed','failed')",
                (status, payload, error, now, now, job_id),
            )
        return self.snapshot(job_id)


__all__ = [
    "AgentInstanceProvisioningRepository", "FINAL_STATES", "VALID_ACTIONS", "normalize_runtime_contract"
]
