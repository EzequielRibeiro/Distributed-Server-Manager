#!/usr/bin/env python3
"""Backend-independent aggregate placement readiness queries."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.placement_diagnostics import placement_status
from agent_runtime_repository import AgentRuntimeRepository
from alert_repository import AlertSession
from backend import DatabaseBackend
from controller_service_health import controller_service_health


class PlacementStatusRepository:
    """Build one explainable placement readiness snapshot."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(self) -> Iterator[AlertSession]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    @staticmethod
    def _count(session: AlertSession, sql: str) -> int:
        row = session.execute(sql).fetchone()
        return 0 if row is None else int(row["total"])

    def snapshot(
        self,
        *,
        initialize: bool = True,
        refresh_health: bool = True,
    ) -> dict[str, Any]:
        """Return counts, health-aware eligibility and stable blockers.

        Existing callers keep the historical behavior by default. Diagnostic
        callers can pass ``initialize=False, refresh_health=False`` to obtain a
        strictly observational snapshot that neither runs migrations nor writes
        derived heartbeat health back to the database.
        """
        if initialize:
            self.initialize()
        if refresh_health:
            AgentRuntimeRepository(self.backend).refresh_health()

        with self.session() as session:
            result: dict[str, Any] = {}
            for name, table in (
                ("controllers", "controllers"),
                ("agents", "agents"),
                ("customers", "customers"),
                ("instances", "instances"),
                ("regions", "regions"),
                ("datacenters", "datacenters"),
                ("agent_locations", "agent_locations"),
            ):
                result[name] = self._count(session, f"SELECT COUNT(*) AS total FROM {table}")

            result["pending_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total FROM agents WHERE status IN ('discovered','pending','pairing')",
            )
            result["unlocated_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total FROM agents a "
                "LEFT JOIN agent_locations al ON al.agent_id=a.id WHERE al.agent_id IS NULL",
            )
            result["online_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total FROM agent_runtime_inventory WHERE health_status='online'",
            )
            result["degraded_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total FROM agent_runtime_inventory WHERE health_status='degraded'",
            )
            result["offline_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total FROM agent_runtime_inventory WHERE health_status='offline'",
            )
            result["eligible_agents"] = self._count(
                session,
                "SELECT COUNT(DISTINCT a.id) AS total "
                "FROM controllers c "
                "JOIN agents a ON a.controller_id=c.id "
                "JOIN agent_locations al ON al.agent_id=a.id "
                "JOIN datacenters d ON d.id=al.datacenter_id "
                "JOIN regions r ON r.id=d.region_id "
                "LEFT JOIN agent_runtime_inventory ari ON ari.agent_id=a.id "
                "WHERE c.status='active' AND a.status='active' "
                "AND al.status='active' AND d.status='active' AND r.status='active' "
                "AND (ari.agent_id IS NULL OR ari.health_status='online')",
            )

        result.update(placement_status(result))
        service_health = controller_service_health()
        result["controller_services"] = service_health
        if service_health.get("checked") and not service_health.get("ready"):
            reasons = list(result.get("placement_reasons") or [])
            if "controller_services_not_ready" not in reasons:
                reasons.append("controller_services_not_ready")
            result["placement_reasons"] = reasons
            result["placement_ready"] = False
            result["placement_reason"] = "controller_services_not_ready"
        return result
