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

    def _upsert(
        self,
        session: AlertSession,
        table: str,
        key: str,
        values: dict[str, Any],
    ) -> None:
        """Insert or reconcile a repository-owned record."""
        ph = self.dialect.placeholder

        existing = session.execute(
            f"SELECT 1 FROM {table} WHERE {key}={ph}",
            (values[key],),
        ).fetchone()

        if existing is None:
            columns = tuple(values)
            session.execute(
                f"INSERT INTO {table}({','.join(columns)}) "
                f"VALUES ({self.dialect.parameters(len(columns))})",
                tuple(values[column] for column in columns),
            )
            return

        updates = [
            column
            for column in values
            if column != key
        ]

        if not updates:
            return

        session.execute(
            f"UPDATE {table} SET "
            + ",".join(
                f"{column}={ph}"
                for column in updates
            )
            + f" WHERE {key}={ph}",
            tuple(
                values[column]
                for column in updates
            )
            + (values[key],),
        )

    def upsert_region(
        self,
        *,
        region_id: str,
        name: str,
        country_code: str | None = None,
        continent_code: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        status: str = "active",
    ) -> None:
        """Create or reconcile a geographic Region."""
        with self.session(transaction=True) as session:
            self._upsert(
                session,
                "regions",
                "id",
                {
                    "id": region_id,
                    "name": name,
                    "country_code": country_code,
                    "continent_code": continent_code,
                    "latitude": latitude,
                    "longitude": longitude,
                    "status": status,
                },
            )

    def upsert_datacenter(
        self,
        *,
        datacenter_id: str,
        region_id: str,
        name: str,
        provider: str | None = None,
        city: str | None = None,
        country_code: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        status: str = "active",
    ) -> None:
        """Create or reconcile a Datacenter."""
        with self.session(transaction=True) as session:
            self._upsert(
                session,
                "datacenters",
                "id",
                {
                    "id": datacenter_id,
                    "region_id": region_id,
                    "name": name,
                    "provider": provider,
                    "city": city,
                    "country_code": country_code,
                    "latitude": latitude,
                    "longitude": longitude,
                    "status": status,
                },
            )

    def upsert_agent_location(
        self,
        *,
        agent_id: str,
        datacenter_id: str,
        latitude: float | None = None,
        longitude: float | None = None,
        public_host: str | None = None,
        status: str = "active",
    ) -> None:
        """Assign or reconcile the geographic location of an Agent."""
        with self.session(transaction=True) as session:
            self._upsert(
                session,
                "agent_locations",
                "agent_id",
                {
                    "agent_id": agent_id,
                    "datacenter_id": datacenter_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "public_host": public_host,
                    "status": status,
                },
            )

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
            "FROM controllers c "
            "JOIN agents a ON a.controller_id=c.id "
            "JOIN agent_locations al ON al.agent_id=a.id "
            "JOIN datacenters d ON d.id=al.datacenter_id "
            "JOIN regions r ON r.id=d.region_id "
            "LEFT JOIN instances i ON i.agent_id=a.id "
            f"WHERE c.id={ph} "
            "AND c.status='active' "
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
