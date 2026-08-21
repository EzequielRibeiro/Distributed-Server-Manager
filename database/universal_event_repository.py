#!/usr/bin/env python3
"""Backend-neutral persistence and Agent ingestion for Universal Events."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from event_platform import EventValidationError, normalize_event, runtime_event_to_universal, utc_now
from alert_repository import AlertSession

LEGACY_DATABASE_EVENT_NAMESPACE = uuid.UUID("ab455e7e-6abc-477a-91cf-56658dba62d5")


class UniversalEventRepository:
    def __init__(self, backend):
        self.backend = backend

    def initialize(self) -> None:
        self.backend.initialize()

    @property
    def _ph(self) -> str:
        return "?" if self.backend.name == "sqlite" else "%s"

    def _row_to_event(self, row: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(row)
        try:
            data = json.loads(str(value.pop("data_json", "{}") or "{}"))
        except json.JSONDecodeError:
            data = {}
        value["data"] = data if isinstance(data, dict) else {}
        value["kind"] = "CapivaraUniversalEvent"
        return value

    def get(self, event_id: str) -> dict[str, Any] | None:
        ph = self._ph
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM universal_events WHERE event_id={ph}",
                    (str(event_id),),
                ).fetchone()
                return self._row_to_event(row) if row is not None else None
            finally:
                session.close()

    def publish(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        event = normalize_event(raw)
        existing = self.get(event["event_id"])
        if existing is not None:
            return {"event": existing, "created": False}

        ph = self._ph
        columns = (
            "event_id", "schema_version", "event_type", "occurred_at", "received_at",
            "source", "source_id", "severity", "agent_id", "instance_id",
            "correlation_id", "causation_id", "actor_type", "actor_id", "data_json",
        )
        values = (
            event["event_id"], event["schema_version"], event["event_type"], event["occurred_at"], utc_now(),
            event["source"], event["source_id"], event["severity"], event["agent_id"], event["instance_id"],
            event["correlation_id"], event["causation_id"], event["actor_type"], event["actor_id"],
            json.dumps(event["data"], sort_keys=True, separators=(",", ":")),
        )
        placeholders = ",".join([ph] * len(columns))
        try:
            with self.backend.transaction() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    session.execute(
                        f"INSERT INTO universal_events ({','.join(columns)}) VALUES ({placeholders})",
                        values,
                    )
                finally:
                    session.close()
        except Exception:
            # At-least-once producers may race on the same event_id. A unique-key
            # collision is a successful idempotent delivery when the row exists.
            existing = self.get(event["event_id"])
            if existing is not None:
                return {"event": existing, "created": False}
            raise
        stored = self.get(event["event_id"])
        return {"event": stored or event, "created": True}

    def _instance_owned_by(self, agent_id: str, instance_id: str) -> bool:
        ph = self._ph
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT id FROM instances WHERE id={ph} AND agent_id={ph}",
                    (instance_id, agent_id),
                ).fetchone()
                return row is not None
            finally:
                session.close()

    def ingest_agent_events(
        self,
        authenticated_agent_id: str,
        raw_events: Iterable[Mapping[str, Any]],
        *,
        max_events: int = 500,
    ) -> dict[str, Any]:
        agent_id = str(authenticated_agent_id or "").strip()
        if not agent_id:
            raise PermissionError("authenticated Agent identity required")

        accepted_ids: list[str] = []
        created = 0
        rejected = 0
        for index, raw in enumerate(raw_events):
            if index >= max(1, min(int(max_events), 1000)):
                break
            try:
                event = runtime_event_to_universal(raw, authenticated_agent_id=agent_id)
                instance_id = event.get("instance_id")
                if instance_id and not self._instance_owned_by(agent_id, str(instance_id)):
                    raise EventValidationError("runtime event instance ownership mismatch")
                result = self.publish(event)
                accepted_ids.append(str(event["event_id"]))
                if result["created"]:
                    created += 1
            except (EventValidationError, TypeError, ValueError):
                rejected += 1

        return {
            "accepted_event_ids": accepted_ids,
            "accepted": len(accepted_ids),
            "created": created,
            "rejected": rejected,
        }

    def import_legacy_events(self, *, limit: int = 10000) -> dict[str, int]:
        """Idempotently copy the foundation-era `events` table into C1."""
        ph = self._ph
        bounded = max(1, min(int(limit), 100000))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT id,event_id,event_type,severity,source,node_id,instance_id,operation_id,payload_json,created_at "
                    f"FROM events ORDER BY id LIMIT {ph}",
                    (bounded,),
                ).fetchall()
            finally:
                session.close()

        created = 0
        existing = 0
        rejected = 0
        for raw_row in rows:
            row = dict(raw_row)
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except json.JSONDecodeError:
                payload = {"legacy_payload": str(row.get("payload_json") or "")}
            event_id = str(row.get("event_id") or "").strip()
            if not event_id:
                event_id = str(uuid.uuid5(
                    LEGACY_DATABASE_EVENT_NAMESPACE,
                    f"{self.backend.name}:{row.get('id')}:{row.get('created_at')}:{row.get('event_type')}",
                ))
            try:
                result = self.publish({
                    "event_id": event_id,
                    "event_type": row.get("event_type"),
                    "occurred_at": str(row.get("created_at")),
                    "source": row.get("source") or "legacy.events",
                    "source_id": row.get("node_id"),
                    "severity": row.get("severity") or "info",
                    "instance_id": row.get("instance_id"),
                    "correlation_id": row.get("operation_id"),
                    "data": payload if isinstance(payload, dict) else {"legacy_payload": payload},
                })
                if result["created"]:
                    created += 1
                else:
                    existing += 1
            except (EventValidationError, TypeError, ValueError):
                rejected += 1
        return {"scanned": len(rows), "created": created, "existing": existing, "rejected": rejected}

    def list_events(
        self,
        *,
        limit: int = 100,
        event_type: str | None = None,
        agent_id: str | None = None,
        instance_id: str | None = None,
        severity: str | None = None,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ph = self._ph
        clauses: list[str] = []
        params: list[Any] = []
        filters = {
            "event_type": event_type.upper() if event_type else None,
            "agent_id": agent_id,
            "instance_id": instance_id,
            "severity": severity.lower() if severity else None,
            "correlation_id": correlation_id,
        }
        for column, value in filters.items():
            if value is None:
                continue
            clauses.append(f"{column}={ph}")
            params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        bounded = max(1, min(int(limit), 1000))
        params.append(bounded)
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT * FROM universal_events{where} ORDER BY occurred_at DESC,event_id DESC LIMIT {ph}",
                    tuple(params),
                ).fetchall()
                return [self._row_to_event(row) for row in rows]
            finally:
                session.close()
