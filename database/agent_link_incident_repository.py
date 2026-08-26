#!/usr/bin/env python3
"""Automatic lifecycle for Agent link-loss incidents.

Keeps at most one active link incident per Agent, preserves resolved history,
and emits Universal Event Platform records for loss/restoration without
persisting any credential or pairing secret.
"""
from __future__ import annotations

import uuid
from typing import Any

from alert_repository import AlertRepository, AlertSession, dialect_for_backend
from universal_event_repository import UniversalEventRepository

RULE_ID = "agent.link"
SOURCE = "controller.agent-link"


class AgentLinkIncidentRepository:
    def __init__(self, backend):
        self.backend = backend
        self.alerts = AlertRepository(backend)
        self.events = UniversalEventRepository(backend)
        self.dialect = dialect_for_backend(backend)

    def initialize(self) -> None:
        self.backend.initialize()
        self.events.initialize()

    def _agent(self, agent_id: str) -> dict[str, Any]:
        identifier = str(agent_id or "").strip()
        if not identifier:
            raise ValueError("agent_id is required")
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT id,controller_id,node_id,name,status FROM agents "
                    f"WHERE id={ph}",
                    (identifier,),
                ).fetchone()
            finally:
                session.close()
        if row is None:
            raise LookupError("Agent not found")
        return dict(row)

    def identify_agent_from_credential_reference(
        self,
        credential_id: str,
        *,
        fingerprint: str | None = None,
    ) -> str | None:
        """Resolve a failed authentication to an Agent without using a secret.

        A known credential id is sufficient when no fingerprint was supplied.
        When the caller supplied a fingerprint it must match the registered
        credential fingerprint, preventing a forged credential reference from
        attributing a failure to another Agent.
        """
        self.initialize()
        identifier = str(credential_id or "").strip()
        if not identifier:
            return None
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT agent_id,fingerprint FROM agent_credentials "
                    f"WHERE id={ph}",
                    (identifier,),
                ).fetchone()
            finally:
                session.close()
        if row is None:
            return None
        supplied = str(fingerprint or "").strip()
        registered = str(row["fingerprint"] or "").strip()
        if supplied and supplied != registered:
            return None
        return str(row["agent_id"])

    def active(self, agent_id: str) -> dict[str, Any] | None:
        self.initialize()
        rows = self.alerts.list_alerts(
            active_only=True,
            agent_id=str(agent_id),
            rule_id=RULE_ID,
            limit=2,
        )
        return rows[0] if rows else None

    def open(
        self,
        agent_id: str,
        *,
        cause: str,
        recommended_action: str,
        message: str | None = None,
        level: str = "CRITICAL",
    ) -> dict[str, Any]:
        """Open one occurrence or return the current active occurrence.

        Repeated heartbeat/authentication failures are deduplicated while the
        incident is active. A later failure after resolution gets a fresh
        alert id, preserving the previous occurrence as historical data.
        """
        self.initialize()
        agent = self._agent(agent_id)
        current = self.active(agent_id)
        if current is not None:
            current = dict(current)
            current["action"] = "UNCHANGED"
            return current

        incident_id = "agent-link-" + uuid.uuid4().hex
        safe_cause = str(cause or "link_unavailable").strip()[:120]
        safe_action = str(recommended_action or "Executar Doctor").strip()[:160]
        safe_message = str(
            message
            or f"Agent {agent['name']} perdeu o vínculo com o Controller. Ação recomendada: {safe_action}."
        )[:2000]
        result = self.alerts.open_alert(
            alert_id=incident_id,
            rule_id=RULE_ID,
            level=str(level or "CRITICAL").upper(),
            message=safe_message,
            scope="agent",
            controller_id=str(agent["controller_id"]),
            agent_id=str(agent["id"]),
            node_id=str(agent["node_id"]),
        )
        self.events.publish({
            "event_type": "AGENT_LINK_LOST",
            "source": SOURCE,
            "source_id": str(agent["controller_id"]),
            "severity": "critical" if str(level).upper() == "CRITICAL" else "warning",
            "agent_id": str(agent["id"]),
            "correlation_id": incident_id,
            "data": {
                "incident_id": incident_id,
                "cause": safe_cause,
                "recommended_action": safe_action,
                "node_id": str(agent["node_id"]),
            },
        })
        return result

    def resolve(
        self,
        agent_id: str,
        *,
        recovery: str = "heartbeat_restored",
        doctor_status: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the active occurrence and preserve its alert/event history."""
        self.initialize()
        agent = self._agent(agent_id)
        current = self.active(agent_id)
        if current is None:
            return None
        incident_id = str(current["id"])
        resolved = self.alerts.resolve_alert(incident_id)
        self.events.publish({
            "event_type": "AGENT_LINK_RESTORED",
            "source": SOURCE,
            "source_id": str(agent["controller_id"]),
            "severity": "info",
            "agent_id": str(agent["id"]),
            "correlation_id": incident_id,
            "data": {
                "incident_id": incident_id,
                "recovery": str(recovery or "heartbeat_restored")[:120],
                "doctor_status": str(doctor_status)[:40] if doctor_status else None,
                "node_id": str(agent["node_id"]),
            },
        })
        return resolved

    def history(self, agent_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        return self.alerts.list_alerts(
            active_only=False,
            agent_id=str(agent_id),
            rule_id=RULE_ID,
            limit=max(1, min(int(limit), 1000)),
        )
