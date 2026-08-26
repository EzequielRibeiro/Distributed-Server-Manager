#!/usr/bin/env python3
"""Database-only alert evaluator for the Universal Event Platform."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
for path in (str(DATABASE), str(ROOT / "core")):
    if path not in sys.path:
        sys.path.insert(0, path)

from alert_repository import AlertRepository, AlertSession, dialect_for_backend
from notification_routing_repository import NotificationRoutingRepository
from runtime_backend import backend_from_environment

CONSUMER_ID = "alert-engine-v2"
DEFAULT_INTERVAL = 5
DEFAULT_BATCH = 200


class DatabaseAlertEngine:
    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.alerts = AlertRepository(backend)
        self.notifications = NotificationRoutingRepository(backend)

    def initialize(self) -> None:
        self.backend.initialize()

    def _latest_event(self) -> tuple[Any, Any] | None:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT received_at,event_id FROM universal_events "
                    "ORDER BY received_at DESC,event_id DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                return row["received_at"], row["event_id"]
            finally:
                session.close()

    def _cursor(self) -> tuple[Any, Any] | None:
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT received_at,event_id FROM event_consumer_cursors WHERE consumer_id={ph}",
                    (CONSUMER_ID,),
                ).fetchone()
                if row is None:
                    return None
                return row["received_at"], row["event_id"]
            finally:
                session.close()

    def _initialize_cursor(self) -> None:
        if self._cursor() is not None:
            return
        latest = self._latest_event()
        received_at, event_id = latest if latest is not None else (None, None)
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "INSERT INTO event_consumer_cursors(consumer_id,received_at,event_id) "
                    f"VALUES ({self.dialect.parameters(3)})",
                    (CONSUMER_ID, received_at, event_id),
                )
            finally:
                session.close()

    def _events(self, limit: int) -> list[dict[str, Any]]:
        cursor = self._cursor()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if cursor is None or cursor[0] is None:
                    rows = session.execute(
                        f"SELECT * FROM universal_events ORDER BY received_at,event_id LIMIT {ph}",
                        (limit,),
                    ).fetchall()
                else:
                    rows = session.execute(
                        "SELECT * FROM universal_events WHERE received_at>" + ph +
                        " OR (received_at=" + ph + " AND event_id>" + ph + ") "
                        "ORDER BY received_at,event_id LIMIT " + ph,
                        (cursor[0], cursor[0], cursor[1], limit),
                    ).fetchall()
            finally:
                session.close()
        return [dict(row) for row in rows]

    def _advance(self, event: dict[str, Any]) -> None:
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "UPDATE event_consumer_cursors SET received_at=" + ph +
                    ",event_id=" + ph + ",updated_at=CURRENT_TIMESTAMP WHERE consumer_id=" + ph,
                    (event["received_at"], event["event_id"], CONSUMER_ID),
                )
            finally:
                session.close()

    @staticmethod
    def _data(event: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(str(event.get("data_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _topology(self, event: dict[str, Any]) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        instance_id = str(event.get("instance_id") or "").strip()
        agent_id = str(event.get("agent_id") or "").strip()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if instance_id:
                    row = session.execute(
                        f"SELECT controller_id,agent_id,node_id,id AS instance_id FROM instances WHERE id={ph}",
                        (instance_id,),
                    ).fetchone()
                    if row is not None:
                        value = dict(row)
                        value["scope"] = "instance"
                        return value
                if agent_id:
                    row = session.execute(
                        f"SELECT controller_id,id AS agent_id FROM agents WHERE id={ph}",
                        (agent_id,),
                    ).fetchone()
                    if row is not None:
                        value = dict(row)
                        value.update({"scope": "agent", "node_id": None, "instance_id": None})
                        return value
            finally:
                session.close()
        data = self._data(event)
        controller_id = str(data.get("controller_id") or "").strip()
        if controller_id:
            return {
                "scope": "controller",
                "controller_id": controller_id,
                "agent_id": None,
                "node_id": None,
                "instance_id": None,
            }
        return None

    @staticmethod
    def _alert_id(rule_id: str, topology: dict[str, Any]) -> str:
        identity = "|".join(
            str(topology.get(key) or "")
            for key in ("controller_id", "agent_id", "node_id", "instance_id")
        )
        digest = hashlib.sha256(f"{rule_id}|{identity}".encode("utf-8")).hexdigest()[:32]
        return f"evt-{digest}"

    def _resolve_rule(self, rule_id: str, topology: dict[str, Any]) -> dict[str, Any] | None:
        return self.alerts.resolve_alert(self._alert_id(rule_id, topology))

    def evaluate(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = str(event.get("event_type") or "UNKNOWN_EVENT").strip().upper()
        topology = self._topology(event)

        if event_type == "INSTANCE_PROVISION_COMPLETED" and topology is not None:
            resolved = None
            for rule_id in ("INSTANCE_PROVISION_FAILED", "STEAM_AUTH_REQUIRED"):
                result = self._resolve_rule(rule_id, topology)
                if result is not None:
                    resolved = result
            return resolved

        severity = str(event.get("severity") or "info").strip().lower()
        if severity not in {"warning", "critical"}:
            return None
        if topology is None:
            return None

        data = self._data(event)
        message = str(
            data.get("message")
            or data.get("error")
            or data.get("title")
            or event_type.replace("_", " ").title()
        )
        return self.alerts.open_alert(
            alert_id=self._alert_id(event_type, topology),
            rule_id=event_type,
            level=severity.upper(),
            message=message,
            scope=str(topology["scope"]),
            controller_id=str(topology["controller_id"]),
            agent_id=topology.get("agent_id"),
            node_id=topology.get("node_id"),
            instance_id=topology.get("instance_id"),
        )

    def route_notification(self, event: dict[str, Any], alert: dict[str, Any] | None) -> list[str]:
        event_type = str(event.get("event_type") or "UNKNOWN_EVENT").strip().upper()
        severity = str(event.get("severity") or "info").strip().lower()
        data = self._data(event)
        message = str(
            data.get("message")
            or data.get("error")
            or data.get("title")
            or event_type.replace("_", " ").title()
        )
        alert_id = None if alert is None else str(alert.get("id") or "").strip() or None
        return self.notifications.enqueue_event(
            event_id=str(event["event_id"]),
            event_type=event_type,
            severity=severity,
            message=message,
            subject=str(data.get("title") or event_type.replace("_", " ").title()),
            alert_id=alert_id,
        )

    def cycle(self, *, limit: int = DEFAULT_BATCH) -> int:
        self.initialize()
        self._initialize_cursor()
        processed = 0
        for event in self._events(max(1, min(int(limit), 1000))):
            alert = self.evaluate(event)
            self.route_notification(event, alert)
            self._advance(event)
            processed += 1
        return processed


def run_daemon() -> None:
    backend = backend_from_environment()
    engine = DatabaseAlertEngine(backend)
    interval = max(1, int(os.environ.get("DSM_ALERT_CHECK_INTERVAL", DEFAULT_INTERVAL)))
    batch = max(1, min(int(os.environ.get("DSM_ALERT_BATCH_SIZE", DEFAULT_BATCH)), 1000))
    while True:
        engine.cycle(limit=batch)
        time.sleep(interval)


def main(argv: list[str]) -> int:
    backend = backend_from_environment()
    engine = DatabaseAlertEngine(backend)
    if len(argv) > 1 and argv[1] == "once":
        engine.cycle()
        return 0
    run_daemon()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
