
#!/usr/bin/env python3
"""Agent network range administration."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import (
    AlertSession,
    dialect_for_backend,
)
from backend import DatabaseBackend


class AgentPortRepository:
    def __init__(
        self,
        backend: DatabaseBackend,
    ):
        self.backend = backend
        self.dialect = dialect_for_backend(
            backend
        )

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

    def agent(
        self,
        agent_id: str,
    ) -> dict[str, Any] | None:
        ph = self.dialect.placeholder

        with self.session() as session:
            row = session.execute(
                "SELECT "
                "id,controller_id,node_id,name,status "
                "FROM agents "
                f"WHERE id={ph}",
                (agent_id,),
            ).fetchone()

        return (
            None
            if row is None
            else dict(row)
        )

    def list_agents(
        self,
        controller_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder

        sql = (
            "SELECT "
            "a.id,a.controller_id,a.node_id,"
            "a.name,a.status,"
            "COUNT(i.id) AS instance_count "
            "FROM agents a "
            "LEFT JOIN instances i "
            "ON i.agent_id=a.id "
        )

        params: tuple[Any, ...] = ()

        if controller_id:
            sql += (
                f"WHERE a.controller_id={ph} "
            )
            params = (
                controller_id,
            )

        sql += (
            "GROUP BY "
            "a.id,a.controller_id,a.node_id,"
            "a.name,a.status "
            "ORDER BY a.name,a.id"
        )

        with self.session() as session:
            rows = session.execute(
                sql,
                params,
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def ranges(
        self,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder

        with self.session() as session:
            rows = session.execute(
                "SELECT "
                "id,agent_id,protocol,start_port,end_port,"
                "status,label,created_at,updated_at "
                "FROM agent_port_ranges "
                f"WHERE agent_id={ph} "
                "ORDER BY protocol,start_port,end_port",
                (agent_id,),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def reservations(
        self,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder

        with self.session() as session:
            rows = session.execute(
                "SELECT "
                "ip.instance_id,ip.name,ip.protocol,"
                "ip.port,ip.bind_address "
                "FROM instance_ports ip "
                "JOIN instances i "
                "ON i.id=ip.instance_id "
                f"WHERE i.agent_id={ph} "
                "ORDER BY ip.protocol,ip.port,"
                "ip.instance_id,ip.name",
                (agent_id,),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def _outside_ranges(
        self,
        *,
        ranges: list[dict[str, Any]],
        reservations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        active = [
            item
            for item in ranges
            if item["status"] == "active"
        ]

        conflicts = []

        for reservation in reservations:
            port = int(
                reservation["port"]
            )
            protocol = reservation[
                "protocol"
            ]

            covered = any(
                item["protocol"] == protocol
                and int(
                    item["start_port"]
                )
                <= port
                <= int(
                    item["end_port"]
                )
                for item in active
            )

            if not covered:
                conflicts.append(
                    reservation
                )

        return conflicts

    def summary(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        agent = self.agent(
            agent_id
        )

        if agent is None:
            raise ValueError(
                "agent not found"
            )

        ranges = self.ranges(
            agent_id
        )

        reservations = self.reservations(
            agent_id
        )

        active_ranges = [
            item
            for item in ranges
            if item["status"] == "active"
        ]

        range_summary = []

        for item in active_ranges:
            protocol = item[
                "protocol"
            ]
            start_port = int(
                item["start_port"]
            )
            end_port = int(
                item["end_port"]
            )

            inside = [
                reservation
                for reservation
                in reservations
                if reservation[
                    "protocol"
                ] == protocol
                and start_port
                <= int(
                    reservation["port"]
                )
                <= end_port
            ]

            capacity = (
                end_port
                - start_port
                + 1
            )

            reserved = len(
                inside
            )

            available = max(
                capacity
                - reserved,
                0,
            )

            usage_pct = (
                100.0
                * reserved
                / capacity
                if capacity
                else 100.0
            )

            range_summary.append(
                {
                    **item,
                    "capacity": capacity,
                    "reserved": reserved,
                    "available": available,
                    "usage_pct": round(
                        usage_pct,
                        2,
                    ),
                    "near_exhaustion": (
                        available
                        <= max(
                            5,
                            int(
                                capacity
                                * 0.10
                            ),
                        )
                    ),
                }
            )

        conflicts = self._outside_ranges(
            ranges=ranges,
            reservations=reservations,
        )

        return {
            "agent": agent,
            "ranges": range_summary,
            "reservations": reservations,
            "conflicts": conflicts,
            "conflict_count": len(
                conflicts
            ),
        }

    def set_ranges(
        self,
        agent_id: str,
        *,
        protocols: tuple[str, ...],
        start_port: int,
        end_port: int,
        force: bool = False,
    ) -> dict[str, Any]:
        if not (
            1
            <= int(start_port)
            <= int(end_port)
            <= 65535
        ):
            raise ValueError(
                "invalid port range"
            )

        normalized = tuple(
            dict.fromkeys(
                protocol.strip().lower()
                for protocol
                in protocols
            )
        )

        if (
            not normalized
            or any(
                protocol
                not in {
                    "tcp",
                    "udp",
                }
                for protocol
                in normalized
            )
        ):
            raise ValueError(
                "protocol must be tcp or udp"
            )

        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp

        with self.session(
            transaction=True
        ) as session:
            agent = session.execute(
                "SELECT "
                "id,node_id,controller_id "
                "FROM agents "
                f"WHERE id={ph}",
                (agent_id,),
            ).fetchone()

            if agent is None:
                raise ValueError(
                    "agent not found"
                )

            conflicts = []

            for protocol in normalized:
                rows = session.execute(
                    "SELECT "
                    "ip.instance_id,ip.name,"
                    "ip.protocol,ip.port "
                    "FROM instance_ports ip "
                    "JOIN instances i "
                    "ON i.id=ip.instance_id "
                    f"WHERE i.agent_id={ph} "
                    f"AND ip.protocol={ph} "
                    f"AND (ip.port<{ph} OR ip.port>{ph}) "
                    "ORDER BY ip.port",
                    (
                        agent_id,
                        protocol,
                        int(start_port),
                        int(end_port),
                    ),
                ).fetchall()

                conflicts.extend(
                    dict(row)
                    for row in rows
                )

            if conflicts and not force:
                raise RuntimeError(
                    "new range excludes reserved ports; "
                    "use administrative force confirmation"
                )

            for protocol in normalized:
                session.execute(
                    "DELETE FROM agent_port_ranges "
                    f"WHERE agent_id={ph} "
                    f"AND protocol={ph}",
                    (
                        agent_id,
                        protocol,
                    ),
                )

                session.execute(
                    "INSERT INTO agent_port_ranges("
                    "agent_id,protocol,start_port,end_port,"
                    "status,label"
                    ") VALUES "
                    f"({self.dialect.parameters(6)})",
                    (
                        agent_id,
                        protocol,
                        int(start_port),
                        int(end_port),
                        "active",
                        "configured",
                    ),
                )

                # Avoid backend-specific timestamp syntax in
                # the INSERT parameter set.
                session.execute(
                    "UPDATE agent_port_ranges "
                    f"SET updated_at={now} "
                    f"WHERE agent_id={ph} "
                    f"AND protocol={ph}",
                    (
                        agent_id,
                        protocol,
                    ),
                )

        return {
            "updated": True,
            "agent_id": agent_id,
            "protocols": list(
                normalized
            ),
            "start_port": int(
                start_port
            ),
            "end_port": int(
                end_port
            ),
            "forced": bool(
                force
            ),
            "excluded_reservations": conflicts,
        }
