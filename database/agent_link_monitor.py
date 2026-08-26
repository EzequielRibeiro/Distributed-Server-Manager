#!/usr/bin/env python3
"""Controller-side sweep for stale Agent heartbeats."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_lifecycle_repository import AgentLifecycleRepository
from agent_link_incident_repository import AgentLinkIncidentRepository
from agent_runtime_repository import AgentRuntimeRepository

# Pairing/pending/disabled/rejected Agents are not established links and must not
# generate link-loss incidents. ``offline`` remains accepted for legacy/manual
# lifecycle administration while heartbeat health stays independently derived.
MONITORED_LIFECYCLE_STATES = frozenset({"active", "offline"})


class AgentLinkMonitor:
    def __init__(self, backend):
        self.backend = backend
        self.runtime = AgentRuntimeRepository(backend)
        self.lifecycle = AgentLifecycleRepository(backend)
        self.incidents = AgentLinkIncidentRepository(backend)

    def sweep(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Refresh heartbeat health and open incidents for established offline Agents.

        This method intentionally does not resolve an existing incident merely
        because health becomes online. Recovery remains gated by authenticated
        heartbeat + Doctor in ``agent_remote_http``.
        """
        health = self.runtime.refresh_health(now=now)
        opened: list[str] = []
        unchanged: list[str] = []
        skipped: list[str] = []

        for agent_id, health_status in health.items():
            lifecycle_status = str(self.lifecycle.status(agent_id) or "").lower()
            if lifecycle_status not in MONITORED_LIFECYCLE_STATES:
                skipped.append(agent_id)
                continue
            if str(health_status).lower() != "offline":
                continue

            incident = self.incidents.open(
                agent_id,
                cause="heartbeat_expired",
                recommended_action="Executar Doctor",
                message=(
                    f"Agent {agent_id} deixou de enviar heartbeat dentro do limite "
                    "configurado. Ação recomendada: Executar Doctor."
                ),
            )
            if str(incident.get("action") or "").upper() == "UNCHANGED":
                unchanged.append(agent_id)
            else:
                opened.append(agent_id)

        return {
            "scanned": len(health),
            "offline": sum(1 for value in health.values() if str(value).lower() == "offline"),
            "opened": opened,
            "unchanged": unchanged,
            "skipped": skipped,
        }
