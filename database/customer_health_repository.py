#!/usr/bin/env python3
"""Portable persistence for Customer functional health incidents."""
from __future__ import annotations

import uuid
from typing import Any

from alert_repository import AlertSession


class CustomerHealthRepository:
    def __init__(self, backend):
        self.backend = backend
        self.ph = "?" if backend.name == "sqlite" else "%s"
        self.now = "CURRENT_TIMESTAMP"

    def initialize(self) -> None:
        self.backend.initialize()

    def _event(self, session, incident: dict[str, Any], action: str, old_state: str | None, new_state: str) -> None:
        session.execute(
            f"INSERT INTO customer_health_events(event_id,incident_id,action,old_state,new_state,event_type,severity,safe_code,message,correlation_id) VALUES ({','.join([self.ph]*10)})",
            (
                str(uuid.uuid4()), incident["incident_id"], action, old_state, new_state,
                incident["event_type"], incident["severity"], incident.get("safe_code"),
                incident["message"], incident.get("correlation_id"),
            ),
        )

    def get(self, incident_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM customer_health_incidents WHERE incident_id={self.ph}",
                    (str(incident_id),),
                ).fetchone()
                return None if row is None else dict(row)
            finally:
                session.close()

    def history(self, incident_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT * FROM customer_health_events WHERE incident_id={self.ph} ORDER BY occurred_at,event_id",
                    (str(incident_id),),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                session.close()

    def open_or_recur(
        self,
        *,
        dedupe_key: str,
        customer_id: str,
        controller_id: str,
        category: str,
        event_type: str,
        severity: str,
        message: str,
        safe_code: str | None = None,
        action: str | None = None,
        instance_id: str | None = None,
        contract_id: str | None = None,
        correlation_id: str | None = None,
        root_type: str | None = None,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        values = {
            "dedupe_key": str(dedupe_key), "customer_id": str(customer_id), "controller_id": str(controller_id),
            "category": str(category), "event_type": str(event_type).upper(), "severity": str(severity).upper(),
            "message": str(message), "safe_code": safe_code, "action": action, "instance_id": instance_id,
            "contract_id": contract_id, "correlation_id": correlation_id, "root_type": root_type, "root_id": root_id,
        }
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                current = session.execute(
                    f"SELECT * FROM customer_health_incidents WHERE dedupe_key={self.ph}",
                    (values["dedupe_key"],),
                ).fetchone()
                if current is None:
                    incident_id = str(uuid.uuid4())
                    params = (
                        incident_id, values["dedupe_key"], values["customer_id"], values["controller_id"],
                        values["category"], values["event_type"], values["severity"], "OPEN", values["safe_code"],
                        values["message"], values["action"], values["instance_id"], values["contract_id"],
                        values["correlation_id"], values["root_type"], values["root_id"],
                    )
                    session.execute(
                        f"INSERT INTO customer_health_incidents(incident_id,dedupe_key,customer_id,controller_id,category,event_type,severity,state,safe_code,message,action,instance_id,contract_id,correlation_id,root_type,root_id) VALUES ({','.join([self.ph]*16)})",
                        params,
                    )
                    row = session.execute(
                        f"SELECT * FROM customer_health_incidents WHERE incident_id={self.ph}", (incident_id,)
                    ).fetchone()
                    result = dict(row); result["transition"] = "OPEN"
                    self._event(session, result, "OPEN", None, "OPEN")
                    return result

                old = dict(current)
                new_state = "OPEN"
                occurrence = int(old.get("occurrence_count") or 1) + (1 if old.get("state") == "RESOLVED" else 0)
                session.execute(
                    "UPDATE customer_health_incidents SET customer_id={p},controller_id={p},category={p},event_type={p},severity={p},state='OPEN',safe_code={p},message={p},action={p},instance_id={p},contract_id={p},correlation_id={p},root_type={p},root_id={p},occurrence_count={p},updated_at={now},resolved_at=NULL WHERE incident_id={p}".format(p=self.ph, now=self.now),
                    (
                        values["customer_id"], values["controller_id"], values["category"], values["event_type"],
                        values["severity"], values["safe_code"], values["message"], values["action"], values["instance_id"],
                        values["contract_id"], values["correlation_id"], values["root_type"], values["root_id"], occurrence,
                        old["incident_id"],
                    ),
                )
                row = session.execute(
                    f"SELECT * FROM customer_health_incidents WHERE incident_id={self.ph}", (old["incident_id"],)
                ).fetchone()
                result = dict(row)
                transition = "RECUR" if old.get("state") == "RESOLVED" else "UPDATE"
                result["transition"] = transition
                if transition == "RECUR":
                    self._event(session, result, "RECUR", str(old.get("state")), new_state)
                return result
            finally:
                session.close()

    def transition(self, incident_id: str, state: str) -> dict[str, Any] | None:
        state = str(state).upper()
        if state not in {"ACKNOWLEDGED", "RESOLVED"}:
            raise ValueError("unsupported Customer health transition")
        self.initialize()
        timestamp = "acknowledged_at" if state == "ACKNOWLEDGED" else "resolved_at"
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                current = session.execute(
                    f"SELECT * FROM customer_health_incidents WHERE incident_id={self.ph}", (str(incident_id),)
                ).fetchone()
                if current is None:
                    return None
                old = dict(current)
                if old.get("state") == state:
                    return old
                if state == "ACKNOWLEDGED" and old.get("state") != "OPEN":
                    raise ValueError("only OPEN Customer incidents can be acknowledged")
                session.execute(
                    f"UPDATE customer_health_incidents SET state={self.ph},{timestamp}={self.now},updated_at={self.now} WHERE incident_id={self.ph}",
                    (state, str(incident_id)),
                )
                row = session.execute(
                    f"SELECT * FROM customer_health_incidents WHERE incident_id={self.ph}", (str(incident_id),)
                ).fetchone()
                result = dict(row)
                self._event(session, result, "ACK" if state == "ACKNOWLEDGED" else "RESOLVE", str(old.get("state")), state)
                return result
            finally:
                session.close()

    def resolve_dedupe(self, dedupe_key: str, *, correlation_id: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT incident_id,state FROM customer_health_incidents WHERE dedupe_key={self.ph}", (str(dedupe_key),)
                ).fetchone()
            finally:
                session.close()
        if row is None or str(row["state"]) == "RESOLVED":
            return None if row is None else self.get(str(row["incident_id"]))
        if correlation_id:
            with self.backend.transaction() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    session.execute(
                        f"UPDATE customer_health_incidents SET correlation_id={self.ph} WHERE incident_id={self.ph}",
                        (correlation_id, str(row["incident_id"])),
                    )
                finally:
                    session.close()
        return self.transition(str(row["incident_id"]), "RESOLVED")

    def list_incidents(self, *, customer_id: str | None = None, controller_id: str | None = None, active_only: bool = True, limit: int = 200) -> list[dict[str, Any]]:
        self.initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if active_only:
            clauses.append("state IN ('OPEN','ACKNOWLEDGED')")
        if customer_id is not None:
            clauses.append(f"customer_id={self.ph}"); params.append(str(customer_id))
        if controller_id is not None:
            clauses.append(f"controller_id={self.ph}"); params.append(str(controller_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT * FROM customer_health_incidents{where} ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,updated_at DESC LIMIT {self.ph}",
                    tuple(params),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                session.close()


__all__ = ["CustomerHealthRepository"]
