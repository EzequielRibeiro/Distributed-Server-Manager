#!/usr/bin/env python3
"""Read-only persistence for the dashboard infrastructure topology."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class InfrastructureRepository:
    """Read-only queries used to build Region -> Datacenter -> Agent views.

    This repository deliberately exposes small persistence records rather than
    dashboard-specific tree structures. Composition, status aggregation and
    RBAC filtering belong to the service/API layers.
    """

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    @contextmanager
    def session(self) -> Iterator[AlertSession]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def controllers(self) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.execute(
                "SELECT id,name,status FROM controllers ORDER BY name,id"
            ).fetchall()
        return [dict(row) for row in rows]

    def controller(self, controller_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT id,name,status FROM controllers WHERE id={ph}",
                (controller_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def regions(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        sql = (
            "SELECT id,name,country_code,continent_code,latitude,longitude,status "
            "FROM regions"
        )
        if active_only:
            sql += " WHERE status='active'"
        sql += " ORDER BY name,id"

        with self.session() as session:
            rows = session.execute(sql).fetchall()
        return [dict(row) for row in rows]

    def datacenters(
        self,
        *,
        region_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder
        clauses: list[str] = []
        params: list[Any] = []

        if region_id is not None:
            clauses.append(f"region_id={ph}")
            params.append(region_id)
        if active_only:
            clauses.append("status='active'")

        sql = (
            "SELECT id,region_id,name,provider,city,country_code,latitude,longitude,status "
            "FROM datacenters"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name,id"

        with self.session() as session:
            rows = session.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def agents(
        self,
        *,
        controller_id: str | None = None,
        datacenter_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return Agents with optional geographic placement.

        LEFT JOIN keeps registered Agents visible even before a location is
        assigned. This is important for migration and partially configured
        installations.
        """

        ph = self.dialect.placeholder
        clauses: list[str] = ["a.status<>'decommissioned'"]
        params: list[Any] = []

        if controller_id is not None:
            clauses.append(f"a.controller_id={ph}")
            params.append(controller_id)
        if datacenter_id is not None:
            clauses.append(f"al.datacenter_id={ph}")
            params.append(datacenter_id)
        if active_only:
            clauses.append("a.status='active'")
            clauses.append("(al.status IS NULL OR al.status='active')")

        sql = (
            "SELECT a.id,a.controller_id,a.node_id,a.name,a.status,"
            "al.datacenter_id,al.latitude,al.longitude,al.public_host,"
            "al.status AS location_status "
            "FROM agents a "
            "LEFT JOIN agent_locations al ON al.agent_id=a.id"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY a.name,a.id"

        with self.session() as session:
            rows = session.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def unplaced_agents(
        self,
        *,
        controller_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder
        clauses = [
            "al.agent_id IS NULL",
            "a.status<>'decommissioned'",
        ]
        params: list[Any] = []

        if controller_id is not None:
            clauses.append(f"a.controller_id={ph}")
            params.append(controller_id)
        if active_only:
            clauses.append("a.status='active'")

        sql = (
            "SELECT a.id,a.controller_id,a.node_id,a.name,a.status "
            "FROM agents a "
            "LEFT JOIN agent_locations al ON al.agent_id=a.id "
            "WHERE " + " AND ".join(clauses) + " "
            "ORDER BY a.name,a.id"
        )

        with self.session() as session:
            rows = session.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def instance_counts_by_agent(
        self,
        *,
        controller_id: str | None = None,
    ) -> dict[str, int]:
        ph = self.dialect.placeholder
        sql = (
            "SELECT a.id AS agent_id,COUNT(i.id) AS instance_count "
            "FROM agents a "
            "JOIN instances i ON i.agent_id=a.id"
        )
        params: tuple[Any, ...] = ()
        if controller_id is not None:
            sql += f" WHERE a.controller_id={ph}"
            params = (controller_id,)
        sql += " GROUP BY a.id"

        with self.session() as session:
            rows = session.execute(sql, params).fetchall()

        return {
            str(row["agent_id"]): int(row["instance_count"])
            for row in rows
        }
