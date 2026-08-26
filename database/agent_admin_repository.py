#!/usr/bin/env python3
"""Administrative maintenance state for registered Capivara Agents."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from agent_runtime_repository import AgentRuntimeRepository
from backend import DatabaseBackend


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class AgentAdminRepository:
    """Safe Controller-side administration without arbitrary remote shell access."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.runtime = AgentRuntimeRepository(backend)

    def initialize(self) -> None:
        self.backend.initialize()

    @staticmethod
    def _metadata(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        try:
            value = json.loads(str(raw or "{}"))
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def _row(self, session: AlertSession, agent_id: str):
        ph = self.dialect.placeholder
        row = session.execute(
            "SELECT a.id,a.controller_id,a.node_id,a.name,a.status,a.metadata_json,"
            "n.name AS node_name FROM agents a JOIN nodes n ON n.id=a.node_id "
            f"WHERE a.id={ph}",
            (agent_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Agent not found")
        return row

    def detail(self, agent_id: str) -> dict[str, Any]:
        self.initialize()
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        ph = self.dialect.placeholder
        snapshot = self.runtime.snapshot(agent_id)
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                credentials = session.execute(
                    "SELECT id,credential_type,status,fingerprint,created_at,last_used_at,revoked_at "
                    "FROM agent_credentials "
                    f"WHERE agent_id={ph} ORDER BY created_at DESC,id DESC",
                    (agent_id,),
                ).fetchall()
            finally:
                session.close()
        metadata = self._metadata(row["metadata_json"])
        snapshot["name"] = row["name"]
        snapshot["node_name"] = row["node_name"]
        snapshot["credentials"] = [dict(item) for item in credentials]
        snapshot["doctor"] = metadata.get("admin_doctor")
        snapshot["relink"] = metadata.get("admin_relink")
        return snapshot

    def rename(self, agent_id: str, name: str, *, actor: str | None = None) -> dict[str, Any]:
        self.initialize()
        agent_id = str(agent_id or "").strip()
        name = str(name or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if not name:
            raise ValueError("Agent name is required")
        if len(name) > 160:
            raise ValueError("Agent name is too long")
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                metadata["last_admin_change"] = {
                    "kind": "rename",
                    "actor": str(actor or "system"),
                    "at": _now(),
                    "previous_name": row["name"],
                    "name": name,
                }
                session.execute(
                    f"UPDATE agents SET name={ph},metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (name, self._json(metadata), agent_id),
                )
            finally:
                session.close()
        return {"agent_id": agent_id, "name": name, "updated": True}

    def request_doctor(self, agent_id: str, *, requested_by: str | None = None) -> dict[str, Any]:
        self.initialize()
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        request_id = "doctor-" + secrets.token_hex(16)
        ph = self.dialect.placeholder
        state = {
            "request_id": request_id,
            "status": "queued",
            "requested_at": _now(),
            "requested_by": str(requested_by or "system"),
        }
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                current = metadata.get("admin_doctor")
                if isinstance(current, dict) and str(current.get("status")) in {"queued", "delivered", "running"}:
                    return dict(current)
                metadata["admin_doctor"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
            finally:
                session.close()
        return state

    def doctor_command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                state = metadata.get("admin_doctor")
                if not isinstance(state, dict) or state.get("status") != "queued":
                    return None
                state = dict(state)
                state["status"] = "delivered"
                state["delivered_at"] = _now()
                metadata["admin_doctor"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
                return {"request_id": state["request_id"], "action": "doctor"}
            finally:
                session.close()

    def apply_doctor_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        request_id = str(result.get("request_id") or "").strip()
        if not request_id:
            return None
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                current = metadata.get("admin_doctor")
                if not isinstance(current, dict) or str(current.get("request_id")) != request_id:
                    return None
                state = dict(current)
                report = result.get("result") if isinstance(result.get("result"), dict) else None
                status = str(result.get("status") or "completed").lower()
                state.update({
                    "status": "completed" if status == "completed" and report is not None else "failed",
                    "completed_at": str(result.get("completed_at") or _now()),
                    "result": report,
                    "error": result.get("error"),
                })
                metadata["admin_doctor"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
                return state
            finally:
                session.close()

    def latest_doctor(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                state = self._metadata(row["metadata_json"]).get("admin_doctor")
                return dict(state) if isinstance(state, dict) else None
            finally:
                session.close()

    def record_relink_prepared(
        self,
        agent_id: str,
        *,
        token_id: str,
        expires_at: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        ph = self.dialect.placeholder
        state = {
            "status": "prepared",
            "token_id": token_id,
            "expires_at": expires_at,
            "prepared_at": _now(),
            "prepared_by": str(actor or "system"),
        }
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                metadata["admin_relink"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
            finally:
                session.close()
        return state
