#!/usr/bin/env python3
"""Explicit administrative host-identity repair for registered Agents."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from agent_identity_incident_repository import AgentIdentityIncidentRepository
from universal_event_repository import UniversalEventRepository

HOST_IDENTITY_METADATA_KEY = "capivara_host_identity_v1"
_REBIND_METADATA_KEY = "host_identity_last_rebind"
_IDENTITY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class AgentIdentityRebindConflict(RuntimeError):
    """Raised when the requested CAS/uniqueness precondition is not satisfied."""


class AgentIdentityAdminRepository:
    """Controller-side administrative operations for physical Agent identity."""

    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.incidents = AgentIdentityIncidentRepository(backend)
        self.events = UniversalEventRepository(backend)

    def initialize(self) -> None:
        self.backend.initialize()
        self.events.initialize()

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

    @staticmethod
    def _identity(value: str | None, *, field: str) -> str:
        identity = str(value or "").strip().lower()
        if not _IDENTITY_RE.fullmatch(identity):
            raise ValueError(f"{field} must be sha256:<64 lowercase hex chars>")
        return identity

    def show(self, agent_id: str) -> dict[str, Any]:
        self.initialize()
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT id,controller_id,node_id,name,status,metadata_json "
                    f"FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone()
            finally:
                session.close()
        if row is None:
            raise LookupError("Agent not found")
        metadata = self._metadata(row["metadata_json"])
        return {
            "agent_id": str(row["id"]),
            "controller_id": str(row["controller_id"]),
            "node_id": str(row["node_id"]),
            "name": row["name"],
            "status": row["status"],
            "host_identity": metadata.get(HOST_IDENTITY_METADATA_KEY),
            "last_rebind": metadata.get(_REBIND_METADATA_KEY),
            "active_incident": self.incidents.active(agent_id),
        }

    def _assert_unique(self, session: AlertSession, *, agent_id: str, new_identity: str) -> None:
        rows = session.execute("SELECT id,metadata_json FROM agents ORDER BY id").fetchall()
        for row in rows:
            other_id = str(row["id"])
            if other_id == agent_id:
                continue
            metadata = self._metadata(row["metadata_json"])
            bound = str(metadata.get(HOST_IDENTITY_METADATA_KEY) or "").strip().lower()
            if bound == new_identity:
                raise AgentIdentityRebindConflict(
                    f"host identity is already bound to Agent {other_id}"
                )

    def rebind(
        self,
        agent_id: str,
        *,
        expected_identity: str,
        new_identity: str,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        """CAS-rebind one Agent to a new physical identity and resolve its incident."""
        self.initialize()
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        expected = self._identity(expected_identity, field="expected_identity")
        new = self._identity(new_identity, field="new_identity")
        reason = str(reason or "").strip()
        actor = str(actor or "").strip()
        if not reason:
            raise ValueError("reason is required")
        if len(reason) > 500:
            raise ValueError("reason is too long")
        if not actor:
            raise ValueError("actor is required")
        if expected == new:
            raise ValueError("new_identity must differ from expected_identity")

        ph = self.dialect.placeholder
        changed_at = _now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                # Serialize competing administrative changes to this Agent.
                session.execute(
                    f"UPDATE agents SET metadata_json=metadata_json WHERE id={ph}",
                    (agent_id,),
                )
                row = session.execute(
                    "SELECT id,controller_id,node_id,name,status,metadata_json "
                    f"FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone()
                if row is None:
                    raise LookupError("Agent not found")
                metadata = self._metadata(row["metadata_json"])
                current = str(metadata.get(HOST_IDENTITY_METADATA_KEY) or "").strip().lower()
                if current != expected:
                    raise AgentIdentityRebindConflict(
                        f"current host identity changed; expected {expected}, found {current or '<unbound>'}"
                    )
                self._assert_unique(session, agent_id=agent_id, new_identity=new)
                metadata[HOST_IDENTITY_METADATA_KEY] = new
                metadata[_REBIND_METADATA_KEY] = {
                    "old_identity": expected,
                    "new_identity": new,
                    "reason": reason,
                    "actor": actor,
                    "at": changed_at,
                }
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
                controller_id = str(row["controller_id"])
                node_id = str(row["node_id"])
            finally:
                session.close()

        self.events.publish(
            {
                "event_type": "AGENT_HOST_IDENTITY_REBOUND",
                "source": "controller.agent-identity-admin",
                "source_id": controller_id,
                "severity": "warning",
                "agent_id": agent_id,
                "actor_type": "user",
                "actor_id": actor,
                "data": {
                    "node_id": node_id,
                    "old_identity": expected,
                    "new_identity": new,
                    "reason": reason,
                    "at": changed_at,
                },
            }
        )
        resolved = self.incidents.resolve(
            agent_id,
            resolution=f"host_identity_rebind:{reason}"[:160],
        )
        return {
            "agent_id": agent_id,
            "controller_id": controller_id,
            "node_id": node_id,
            "old_identity": expected,
            "new_identity": new,
            "reason": reason,
            "actor": actor,
            "at": changed_at,
            "incident_resolved": resolved is not None,
        }

    def incidents_history(self, agent_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.incidents.history(agent_id, limit=limit)
