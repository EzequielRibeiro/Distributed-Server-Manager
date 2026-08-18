#!/usr/bin/env python3
"""Region, datacenter and Agent location repository."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class LocationRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(
        self,
        *,
        transaction: bool = False,
    ) -> Iterator[AlertSession]:
        context = (
            self.backend.transaction()
            if transaction
            else self.backend.connect()
        )

        with context as connection:
            session = AlertSession(
                self.backend,
                connection,
            )

            try:
                yield session
            finally:
                session.close()

    def regions(self) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.execute(
                "SELECT id,name,country_code,continent_code,"
                "latitude,longitude,status "
                "FROM regions "
                "WHERE status='active' "
                "ORDER BY name,id"
            ).fetchall()

        return [dict(row) for row in rows]

    def datacenters(
        self,
        region_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder

        sql = (
            "SELECT d.id,d.region_id,d.name,d.provider,"
            "d.city,d.country_code,d.latitude,d.longitude,"
            "d.status,r.name AS region_name "
            "FROM datacenters d "
            "JOIN regions r ON r.id=d.region_id "
            "WHERE d.status='active' "
            "AND r.status='active' "
        )

        params: tuple[Any, ...] = ()

        if region_id:
            sql += f"AND d.region_id={ph} "
            params = (region_id,)

        sql += "ORDER BY r.name,d.name,d.id"

        with self.session() as session:
            rows = session.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    def candidates(
        self,
        controller_id: str,
        *,
        region_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder

        sql = (
            "SELECT "
            "a.id AS agent_id,"
            "a.node_id,"
            "a.name AS agent_name,"
            "a.status AS agent_status,"
            "al.datacenter_id,"
            "COALESCE(al.latitude,d.latitude,r.latitude) AS latitude,"
            "COALESCE(al.longitude,d.longitude,r.longitude) AS longitude,"
            "al.public_host,"
            "d.name AS datacenter_name,"
            "d.city,"
            "d.country_code,"
            "r.id AS region_id,"
            "r.name AS region_name,"
            "COUNT(i.id) AS instance_count "
            "FROM agents a "
            "JOIN agent_locations al ON al.agent_id=a.id "
            "JOIN datacenters d ON d.id=al.datacenter_id "
            "JOIN regions r ON r.id=d.region_id "
            "LEFT JOIN instances i ON i.agent_id=a.id "
            f"WHERE a.controller_id={ph} "
            "AND a.status='active' "
            "AND al.status='active' "
            "AND d.status='active' "
            "AND r.status='active' "
        )

        params: list[Any] = [controller_id]

        if region_id:
            sql += f"AND r.id={ph} "
            params.append(region_id)

        sql += (
            "GROUP BY "
            "a.id,a.node_id,a.name,a.status,"
            "al.datacenter_id,al.latitude,al.longitude,"
            "al.public_host,d.latitude,d.longitude,"
            "d.name,d.city,d.country_code,"
            "r.id,r.name,r.latitude,r.longitude "
            "ORDER BY instance_count,a.name,a.id"
        )

        with self.session() as session:
            rows = session.execute(
                sql,
                tuple(params),
            ).fetchall()

        return [dict(row) for row in rows]
