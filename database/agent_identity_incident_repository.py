#!/usr/bin/env python3
"""Persistent security incidents for cloned/conflicting Agent identities."""
from __future__ import annotations

import uuid
from typing import Any

from alert_repository import AlertRepository, AlertSession, dialect_for_backend
from universal_event_repository import UniversalEventRepository

RULE_ID = "agent.identity_collision"
SOURCE = "controller.agent-identity"


class AgentIdentityIncidentRepository:
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
                    "SELECT id,controller_id,node_id,name,status "
                    f"FROM agents WHERE id={ph}",
                    (identifier,),
                ).fetchone()
            finally:
                session.close()

        if row is None:
            raise LookupError("Agent not found")

        return dict(row)

    def active(self, agent_id: str) -> dict[str, Any] | None:
        self.initialize()

        rows = self.alerts.list_alerts(
            active_only=True,
            agent_id=str(agent_id),
            rule_id=RULE_ID,
            limit=2,
        )

        return rows[0] if rows else None

    def open_collision(
        self,
        agent_id: str,
        *,
        expected_identity: str | None = None,
        presented_identity: str | None = None,
    ) -> dict[str, Any]:
        """Open one persistent identity collision incident per Agent."""
        self.initialize()

        agent = self._agent(agent_id)
        current = self.active(agent_id)

        if current is not None:
            result = dict(current)
            result["action"] = "UNCHANGED"
            return result

        incident_id = "agent-identity-" + uuid.uuid4().hex

        result = self.alerts.open_alert(
            alert_id=incident_id,
            rule_id=RULE_ID,
            level="CRITICAL",
            message=(
                "Foi detectado mais de um host físico apresentando a mesma "
                "identidade lógica de Agent. O host conflitante foi bloqueado."
            ),
            scope="agent",
            controller_id=str(agent["controller_id"]),
            agent_id=str(agent["id"]),
            node_id=str(agent["node_id"]),
        )

        self.events.publish(
            {
                "event_type": "AGENT_IDENTITY_COLLISION",
                "source": SOURCE,
                "source_id": str(agent["controller_id"]),
                "severity": "critical",
                "agent_id": str(agent["id"]),
                "correlation_id": incident_id,
                "data": {
                    "incident_id": incident_id,
                    "node_id": str(agent["node_id"]),
                    "expected_identity": (
                        str(expected_identity)[:160]
                        if expected_identity
                        else None
                    ),
                    "presented_identity": (
                        str(presented_identity)[:160]
                        if presented_identity
                        else None
                    ),
                    "recommended_action": (
                        "Verificar clonagem e revincular o host conflitante"
                    ),
                },
            }
        )

        return result

    def resolve(
        self,
        agent_id: str,
        *,
        resolution: str,
    ) -> dict[str, Any] | None:
        """Resolve only through an explicit administrative repair workflow."""
        self.initialize()

        agent = self._agent(agent_id)
        current = self.active(agent_id)

        if current is None:
            return None

        incident_id = str(current["id"])

        result = self.alerts.resolve_alert(incident_id)

        self.events.publish(
            {
                "event_type": "AGENT_IDENTITY_COLLISION_RESOLVED",
                "source": SOURCE,
                "source_id": str(agent["controller_id"]),
                "severity": "info",
                "agent_id": str(agent["id"]),
                "correlation_id": incident_id,
                "data": {
                    "incident_id": incident_id,
                    "node_id": str(agent["node_id"]),
                    "resolution": str(resolution or "administrative_relink")[:160],
                },
            }
        )

        return result

    def history(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.initialize()

        return self.alerts.list_alerts(
            active_only=False,
            agent_id=str(agent_id),
            rule_id=RULE_ID,
            limit=max(1, min(int(limit), 1000)),
        )
