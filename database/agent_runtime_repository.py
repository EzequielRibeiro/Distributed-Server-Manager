#!/usr/bin/env python3
"""Agent runtime inventory, heartbeat persistence and health transitions."""

from __future__ import annotations

import json
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.agent_health import derive_agent_health, utc_timestamp
from alert_repository import AlertRepository, AlertSession, dialect_for_backend
from backend import DatabaseBackend
from universal_event_repository import UniversalEventRepository

_AGENT_HEALTH_EVENT_NAMESPACE = uuid.UUID("c6630a17-a63d-4fb1-931f-69e45162986c")


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

    @staticmethod
    def _health_correlation_id(agent_id: str, last_seen: Any) -> str:
        anchor = str(last_seen or "never").replace(" ", "T")
        return f"agent-health:{agent_id}:{anchor}"

    @staticmethod
    def _health_event_id(agent_id: str, previous: str, target: str, last_seen: Any) -> str:
        return str(uuid.uuid5(
            _AGENT_HEALTH_EVENT_NAMESPACE,
            f"{agent_id}:{previous}->{target}:{last_seen or 'never'}",
        ))

    def _publish_health_transition(
        self,
        *,
        agent_id: str,
        controller_id: str,
        node_id: str | None,
        agent_name: str | None,
        previous: str,
        target: str,
        last_seen: Any,
        occurred_at: datetime,
    ) -> None:
        """Publish idempotent health transition side effects.

        Event IDs are deterministic for a transition anchored to the heartbeat
        that started the outage. Re-running a failed reconciliation therefore
        cannot duplicate the Universal Event. The alert has one stable ID per
        Agent and is reopened/escalated/resolved by the existing alert state
        machine.
        """
        previous = str(previous or "offline").lower()
        target = str(target or "offline").lower()
        if previous == target:
            return

        correlation_id = self._health_correlation_id(agent_id, last_seen)
        event_type = {
            "degraded": "AGENT_DEGRADED",
            "offline": "AGENT_OFFLINE",
            "online": "AGENT_RECOVERED",
        }.get(target)
        if event_type is None:
            return

        severity = {"degraded": "warning", "offline": "critical", "online": "info"}[target]
        label = str(agent_name or agent_id)
        message = {
            "degraded": f"Agent {label} está degradado; heartbeat atrasado.",
            "offline": f"Agent {label} está offline; heartbeat expirou.",
            "online": f"Agent {label} voltou a responder aos heartbeats.",
        }[target]

        UniversalEventRepository(self.backend).publish({
            "event_id": self._health_event_id(agent_id, previous, target, last_seen),
            "event_type": event_type,
            "occurred_at": utc_timestamp(occurred_at),
            "source": "controller.agent_health",
            "source_id": controller_id,
            "severity": severity,
            "agent_id": agent_id,
            "correlation_id": correlation_id,
            "actor_type": "system",
            "actor_id": controller_id,
            "data": {
                "message": message,
                "previous_health": previous,
                "health_status": target,
                "last_seen": str(last_seen) if last_seen is not None else None,
                "node_id": node_id,
            },
        })

        alerts = AlertRepository(self.backend)
        alert_id = f"agent-health:{agent_id}"
        if target in {"degraded", "offline"}:
            alerts.open_alert(
                alert_id=alert_id,
                rule_id="agent-heartbeat-health",
                level="CRITICAL" if target == "offline" else "WARNING",
                message=message,
                scope="agent",
                controller_id=controller_id,
                agent_id=agent_id,
                node_id=node_id,
            )
        elif target == "online":
            alerts.resolve_alert(alert_id)

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
        network: Any = None,
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
            ram_total_bytes, self._json(storage), self._json(network),
            heartbeat_interval_seconds, degraded_after_seconds,
            offline_after_seconds, now, agent_id,
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
                    "capabilities_json,cpu_json,ram_total_bytes,storage_json,network_json,"
                    "heartbeat_interval_seconds,degraded_after_seconds,offline_after_seconds,"
                    "updated_at,agent_id) VALUES ("
                    + self.dialect.parameters(16) + ")",
                    values,
                )
            else:
                session.execute(
                    "UPDATE agent_runtime_inventory SET "
                    f"hostname={ph},os_name={ph},architecture={ph},capivara_version={ph},"
                    f"address={ph},fingerprint={ph},capabilities_json={ph},cpu_json={ph},"
                    f"ram_total_bytes={ph},storage_json={ph},network_json={ph},heartbeat_interval_seconds={ph},"
                    f"degraded_after_seconds={ph},offline_after_seconds={ph},updated_at={ph} "
                    f"WHERE agent_id={ph}",
                    values,
                )

    def heartbeat(self, agent_id: str, *, observed_at: datetime | None = None) -> str:
        ph = self.dialect.placeholder
        observed = observed_at or datetime.now(timezone.utc)
        timestamp = utc_timestamp(observed)
        transition: dict[str, Any] | None = None

        with self.session(transaction=True) as session:
            agent = session.execute(
                f"SELECT controller_id,node_id,name FROM agents WHERE id={ph}",
                (agent_id,),
            ).fetchone()
            if agent is None:
                raise AgentRuntimeNotFound(f"Agent not found: {agent_id}")
            row = session.execute(
                f"SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id={ph}",
                (agent_id,),
            ).fetchone()
            if row is None:
                session.execute(
                    "INSERT INTO agent_runtime_inventory(agent_id,health_status,last_seen,updated_at) "
                    f"VALUES ({self.dialect.parameters(4)})",
                    (agent_id, "online", timestamp, timestamp),
                )
            else:
                previous = str(row["health_status"] or "offline").lower()
                if previous != "online":
                    transition = {
                        "agent_id": agent_id,
                        "controller_id": str(agent["controller_id"]),
                        "node_id": agent["node_id"],
                        "agent_name": agent["name"],
                        "previous": previous,
                        "target": "online",
                        "last_seen": row["last_seen"],
                        "occurred_at": observed,
                    }
                session.execute(
                    f"UPDATE agent_runtime_inventory SET health_status={ph},last_seen={ph},updated_at={ph} WHERE agent_id={ph}",
                    ("online", timestamp, timestamp, agent_id),
                )

        if transition:
            self._publish_health_transition(**transition)
        return timestamp

    def refresh_health(self, *, now: datetime | None = None, controller_id: str | None = None) -> dict[str, str]:
        current = now or datetime.now(timezone.utc)
        ph = self.dialect.placeholder
        sql = (
            "SELECT ari.agent_id,ari.last_seen,ari.degraded_after_seconds,ari.offline_after_seconds,ari.health_status,"
            "a.controller_id,a.node_id,a.name AS agent_name "
            "FROM agent_runtime_inventory ari JOIN agents a ON a.id=ari.agent_id"
        )
        params: tuple[Any, ...] = ()
        if controller_id:
            sql += f" WHERE a.controller_id={ph}"
            params = (controller_id,)
        changes: dict[str, str] = {}
        transitions: list[dict[str, Any]] = []

        with self.session(transaction=True) as session:
            rows = session.execute(sql, params).fetchall()
            for row in rows:
                health = derive_agent_health(
                    row["last_seen"],
                    now=current,
                    degraded_after_seconds=int(row["degraded_after_seconds"]),
                    offline_after_seconds=int(row["offline_after_seconds"]),
                )
                agent_id = str(row["agent_id"])
                previous = str(row["health_status"] or "offline").lower()
                changes[agent_id] = health
                if health != previous:
                    transitions.append({
                        "agent_id": agent_id,
                        "controller_id": str(row["controller_id"]),
                        "node_id": row["node_id"],
                        "agent_name": row["agent_name"],
                        "previous": previous,
                        "target": health,
                        "last_seen": row["last_seen"],
                        "occurred_at": current,
                    })
                    session.execute(
                        f"UPDATE agent_runtime_inventory SET health_status={ph},updated_at={ph} WHERE agent_id={ph}",
                        (health, utc_timestamp(current), agent_id),
                    )

        for transition in transitions:
            self._publish_health_transition(**transition)
        return changes

    def snapshot(
        self,
        agent_id: str,
        *,
        now: datetime | None = None,
        refresh_health: bool = True,
    ) -> dict[str, Any]:
        """Return one Agent runtime snapshot.

        Operational callers retain health reconciliation by default. Diagnostic
        callers can disable it to guarantee that the snapshot is observational
        and does not update derived health state.
        """
        if refresh_health:
            self.refresh_health(now=now)
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT a.id AS agent_id,a.node_id,a.controller_id,a.status,n.name AS node_name,"
                "ari.hostname,ari.os_name,ari.architecture,ari.capivara_version,ari.address,"
                "ari.fingerprint,ari.capabilities_json,ari.cpu_json,ari.ram_total_bytes,"
                "ari.storage_json,ari.network_json,ari.health_status,ari.last_seen "
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
        for field in ("capabilities_json", "cpu_json", "storage_json", "network_json"):
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
