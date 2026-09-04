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
                    "SELECT id,credential_type,status,fingerprint,issued_at,last_used_at,revoked_at "
                    "FROM agent_credentials "
                    f"WHERE agent_id={ph} ORDER BY issued_at DESC,id DESC",
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

    def _detach_alert_history(self, session: AlertSession, agent_id: str, node_id: str) -> dict[str, int]:
        """Resolve live alerts and detach historical Agent/node foreign keys."""
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        alerts = session.execute(
            "SELECT id,level,state,message FROM alerts "
            f"WHERE agent_id={ph} OR node_id={ph} ORDER BY id",
            (agent_id, node_id),
        ).fetchall()
        resolved = 0
        for alert in alerts:
            if str(alert["state"]) not in {"OPEN", "ACKNOWLEDGED"}:
                continue
            session.execute(
                "UPDATE alerts SET state='RESOLVED', "
                f"resolved_at={now}, updated_at={now}, suppressed_until=NULL "
                f"WHERE id={ph}",
                (alert["id"],),
            )
            session.execute(
                "INSERT INTO alert_events(alert_id,action,level,old_state,new_state,message) "
                f"VALUES ({self.dialect.parameters(6)})",
                (
                    alert["id"],
                    "RESOLVE",
                    alert["level"],
                    alert["state"],
                    "RESOLVED",
                    alert["message"],
                ),
            )
            resolved += 1
        session.execute(
            "UPDATE alerts SET agent_id=NULL,node_id=NULL "
            f"WHERE agent_id={ph} OR node_id={ph}",
            (agent_id, node_id),
        )
        return {"preserved": len(alerts), "resolved": resolved}

    def remove(self, agent_id: str, *, confirmation: str, actor: str | None = None) -> dict[str, Any]:
        """Remove a standalone Agent registration while preserving alert history."""
        self.initialize()
        agent_id = str(agent_id or "").strip()
        confirmation = str(confirmation or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if confirmation != agent_id:
            raise ValueError("confirmation must exactly match agent_id")
        ph = self.dialect.placeholder
        alert_history = {"preserved": 0, "resolved": 0}
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                node_id = str(row["node_id"])
                controller_owner = session.execute(
                    f"SELECT id FROM controllers WHERE node_id={ph}",
                    (node_id,),
                ).fetchone()
                if controller_owner is not None:
                    raise ValueError(
                        "Agent shares its Node with a Controller and cannot use generic removal; "
                        "use the Hybrid -> Controller lifecycle transition"
                    )

                instances = session.execute(
                    "SELECT id,name,status FROM instances "
                    f"WHERE node_id={ph} ORDER BY id",
                    (node_id,),
                ).fetchall()
                if instances:
                    ids = ", ".join(str(item["id"]) for item in instances[:5])
                    suffix = "" if len(instances) <= 5 else f" (+{len(instances) - 5})"
                    raise ValueError(
                        f"Agent has {len(instances)} instance(s) and cannot be removed: {ids}{suffix}"
                    )

                alert_history = self._detach_alert_history(session, agent_id, node_id)
                session.execute(f"DELETE FROM agents WHERE id={ph}", (agent_id,))
                session.execute(f"DELETE FROM nodes WHERE id={ph}", (node_id,))
            finally:
                session.close()

        return {
            "agent_id": agent_id,
            "node_id": node_id,
            "name": str(row["name"]),
            "controller_id": str(row["controller_id"]),
            "removed": True,
            "removed_by": str(actor or "system"),
            "removed_at": _now(),
            "alert_history": alert_history,
        }
