#!/usr/bin/env python3
"""Agent runtime inventory and heartbeat persistence."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.agent_health import derive_agent_health, utc_timestamp
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class AgentRuntimeNotFound(LookupError):
    pass


class AgentRuntimeRepository:
    """Store reported Agent facts without overloading lifecycle status."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(self, *, transaction: bool = False) -> Iterator[AlertSession]:
        context = self.backend.transaction() if transaction else self.backend.connect()
        with context as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))

    def _agent_exists(self, session: AlertSession, agent_id: str) -> bool:
        ph = self.dialect.placeholder
        return session.execute(
            f"SELECT 1 FROM agents WHERE id={ph}", (agent_id,)
        ).fetchone() is not None

    def upsert_inventory(
        self,
        *,
        agent_id: str,
        hostname: str | None = None,
        os_name: str | None = None,
        architecture: str | None = None,
        capivara_version: str | None = None,
        address: str | None = None,
        fingerprint: str | None = None,
        capabilities: Any = None,
        cpu: Any = None,
        ram_total_bytes: int | None = None,
        storage: Any = None,
        heartbeat_interval_seconds: int = 30,
        degraded_after_seconds: int = 60,
        offline_after_seconds: int = 120,
    ) -> None:
        agent_id = str(agent_id).strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if degraded_after_seconds < heartbeat_interval_seconds:
            raise ValueError("degraded threshold cannot be below heartbeat interval")
        if offline_after_seconds <= degraded_after_seconds:
            raise ValueError("offline threshold must exceed degraded threshold")

        ph = self.dialect.placeholder
        now = utc_timestamp()
        values = (
            hostname, os_name, architecture, capivara_version, address,
            fingerprint, self._json(capabilities), self._json(cpu),
            ram_total_bytes, self._json(storage), heartbeat_interval_seconds,
            degraded_after_seconds, offline_after_seconds, now, agent_id,
        )

        with self.session(transaction=True) as session:
            if not self._agent_exists(session, agent_id):
                raise AgentRuntimeNotFound(f"Agent not found: {agent_id}")
            existing = session.execute(
                f"SELECT 1 FROM agent_runtime_inventory WHERE agent_id={ph}",
                (agent_id,),
            ).fetchone()
            if existing is None:
                session.execute(
                    "INSERT INTO agent_runtime_inventory("
                    "hostname,os_name,architecture,capivara_version,address,fingerprint,"
                    "capabilities_json,cpu_json,ram_total_bytes,storage_json,"
                    "heartbeat_interval_seconds,degraded_after_seconds,offline_after_seconds,"
                    "updated_at,agent_id) VALUES ("
                    + self.dialect.parameters(15) + ")",
                    values,
                )
            else:
                session.execute(
                    "UPDATE agent_runtime_inventory SET "
                    f"hostname={ph},os_name={ph},architecture={ph},capivara_version={ph},"
                    f"address={ph},fingerprint={ph},capabilities_json={ph},cpu_json={ph},"
                    f"ram_total_bytes={ph},storage_json={ph},heartbeat_interval_seconds={ph},"
                    f"degraded_after_seconds={ph},offline_after_seconds={ph},updated_at={ph} "
                    f"WHERE agent_id={ph}",
                    values,
                )

    def heartbeat(self, agent_id: str, *, observed_at: datetime | None = None) -> str:
        ph = self.dialect.placeholder
        timestamp = utc_timestamp(observed_at)
        with self.session(transaction=True) as session:
            if not self._agent_exists(session, agent_id):
                raise AgentRuntimeNotFound(f"Agent not found: {agent_id}")
            row = session.execute(
                f"SELECT 1 FROM agent_runtime_inventory WHERE agent_id={ph}",
                (agent_id,),
            ).fetchone()
            if row is None:
                session.execute(
                    "INSERT INTO agent_runtime_inventory(agent_id,health_status,last_seen,updated_at) "
                    f"VALUES ({self.dialect.parameters(4)})",
                    (agent_id, "online", timestamp, timestamp),
                )
            else:
                session.execute(
                    f"UPDATE agent_runtime_inventory SET health_status={ph},last_seen={ph},updated_at={ph} WHERE agent_id={ph}",
                    ("online", timestamp, timestamp, agent_id),
                )
        return timestamp

    def refresh_health(self, *, now: datetime | None = None, controller_id: str | None = None) -> dict[str, str]:
        current = now or datetime.now(timezone.utc)
        ph = self.dialect.placeholder
        sql = (
            "SELECT ari.agent_id,ari.last_seen,ari.degraded_after_seconds,ari.offline_after_seconds,ari.health_status "
            "FROM agent_runtime_inventory ari JOIN agents a ON a.id=ari.agent_id"
        )
        params: tuple[Any, ...] = ()
        if controller_id:
            sql += f" WHERE a.controller_id={ph}"
            params = (controller_id,)
        changes: dict[str, str] = {}
        with self.session(transaction=True) as session:
            rows = session.execute(sql, params).fetchall()
            for row in rows:
                health = derive_agent_health(
                    row["last_seen"],
                    now=current,
                    degraded_after_seconds=int(row["degraded_after_seconds"]),
                    offline_after_seconds=int(row["offline_after_seconds"]),
                )
                changes[str(row["agent_id"])] = health
                if health != str(row["health_status"]):
                    session.execute(
                        f"UPDATE agent_runtime_inventory SET health_status={ph},updated_at={ph} WHERE agent_id={ph}",
                        (health, utc_timestamp(current), str(row["agent_id"])),
                    )
        return changes

    def snapshot(self, agent_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        self.refresh_health(now=now)
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT a.id AS agent_id,a.node_id,a.controller_id,a.status,n.name AS node_name,"
                "ari.hostname,ari.os_name,ari.architecture,ari.capivara_version,ari.address,"
                "ari.fingerprint,ari.capabilities_json,ari.cpu_json,ari.ram_total_bytes,"
                "ari.storage_json,ari.health_status,ari.last_seen "
                "FROM agents a JOIN nodes n ON n.id=a.node_id "
                "LEFT JOIN agent_runtime_inventory ari ON ari.agent_id=a.id "
                f"WHERE a.id={ph}",
                (agent_id,),
            ).fetchone()
            if row is None:
                raise AgentRuntimeNotFound(f"Agent not found: {agent_id}")
            ports = session.execute(
                "SELECT protocol,start_port,end_port,status,label FROM agent_port_ranges "
                f"WHERE agent_id={ph} ORDER BY protocol,start_port,end_port",
                (agent_id,),
            ).fetchall()

        result = dict(row)
        for field in ("capabilities_json", "cpu_json", "storage_json"):
            raw = result.pop(field, None)
            result[field.removesuffix("_json")] = json.loads(raw or "{}")
        result["port_ranges"] = [dict(item) for item in ports]
        result["health_status"] = result.get("health_status") or "offline"
        return result

    def controller_agents(self, controller_id: str, *, now: datetime | None = None) -> list[dict[str, Any]]:
        self.refresh_health(now=now, controller_id=controller_id)
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT id FROM agents WHERE controller_id=" + ph + " ORDER BY name,id",
                (controller_id,),
            ).fetchall()
        return [self.snapshot(str(row["id"]), now=now) for row in rows]
