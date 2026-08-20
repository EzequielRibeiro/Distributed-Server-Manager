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
from alert_repository import AlertSession
from backend import DatabaseBackend


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

    def snapshot(self) -> dict[str, Any]:
        """Return counts, eligibility and stable placement blockers."""
        self.initialize()

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
                result[name] = self._count(
                    session,
                    f"SELECT COUNT(*) AS total FROM {table}",
                )

            result["pending_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total FROM agents "
                "WHERE status IN ('pending','pairing')",
            )

            result["unlocated_agents"] = self._count(
                session,
                "SELECT COUNT(*) AS total "
                "FROM agents a "
                "LEFT JOIN agent_locations al ON al.agent_id=a.id "
                "WHERE al.agent_id IS NULL",
            )

            result["eligible_agents"] = self._count(
                session,
                "SELECT COUNT(DISTINCT a.id) AS total "
                "FROM controllers c "
                "JOIN agents a ON a.controller_id=c.id "
                "JOIN agent_locations al ON al.agent_id=a.id "
                "JOIN datacenters d ON d.id=al.datacenter_id "
                "JOIN regions r ON r.id=d.region_id "
                "WHERE c.status='active' "
                "AND a.status='active' "
                "AND al.status='active' "
                "AND d.status='active' "
                "AND r.status='active'",
            )

        result.update(placement_status(result))
        return result
