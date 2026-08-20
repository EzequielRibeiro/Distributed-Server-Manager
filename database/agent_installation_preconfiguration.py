#!/usr/bin/env python3
"""Persist and apply Agent settings requested before enrollment."""

from __future__ import annotations

from typing import Any

from agent_port_repository import AgentPortRepository
from alert_repository import AlertSession, dialect_for_backend


_ALLOWED_PROTOCOLS = {"tcp", "udp", "both"}


def normalize_preconfiguration(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    name = str(payload.get("agent_name", "") or "").strip()
    if len(name) > 128:
        raise ValueError("agent_name must be at most 128 characters")

    start_raw = payload.get("port_start")
    end_raw = payload.get("port_end")
    protocol_raw = payload.get("port_protocol")
    has_port_value = any(value not in (None, "") for value in (start_raw, end_raw, protocol_raw))

    if not has_port_value:
        return {
            "agent_name": name or None,
            "port_protocol": None,
            "port_start": None,
            "port_end": None,
        }

    if start_raw in (None, "") or end_raw in (None, ""):
        raise ValueError("port_start and port_end must be provided together")
    try:
        start = int(start_raw)
        end = int(end_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("port range must contain integers") from exc
    if not 1 <= start <= end <= 65535:
        raise ValueError("invalid Agent port range")

    protocol = str(protocol_raw or "both").strip().lower()
    if protocol not in _ALLOWED_PROTOCOLS:
        raise ValueError("port_protocol must be tcp, udp or both")

    return {
        "agent_name": name or None,
        "port_protocol": protocol,
        "port_start": start,
        "port_end": end,
    }


class AgentInstallationPreconfigurationRepository:
    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def save(self, installation_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_preconfiguration(settings)
        installation_id = str(installation_id or "").strip()
        if not installation_id:
            raise ValueError("installation_id is required")

        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "DELETE FROM agent_installation_preconfiguration WHERE installation_id=" + ph,
                    (installation_id,),
                )
                session.execute(
                    "INSERT INTO agent_installation_preconfiguration("
                    "installation_id,requested_name,port_protocol,port_start,port_end"
                    ") VALUES (" + self.dialect.parameters(5) + ")",
                    (
                        installation_id,
                        normalized["agent_name"],
                        normalized["port_protocol"],
                        normalized["port_start"],
                        normalized["port_end"],
                    ),
                )
            finally:
                session.close()
        return normalized

    def get(self, installation_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT installation_id,requested_name,port_protocol,port_start,port_end,"
                    "applied_at,apply_error FROM agent_installation_preconfiguration "
                    "WHERE installation_id=" + ph,
                    (str(installation_id),),
                ).fetchone()
            finally:
                session.close()
        return None if row is None else dict(row)

    def _mark_result(self, installation_id: str, *, error: str | None) -> None:
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if error:
                    session.execute(
                        "UPDATE agent_installation_preconfiguration SET apply_error=" + ph +
                        ",applied_at=NULL,updated_at=" + now + " WHERE installation_id=" + ph,
                        (error[:500], installation_id),
                    )
                else:
                    session.execute(
                        "UPDATE agent_installation_preconfiguration SET apply_error=NULL,"
                        "applied_at=" + now + ",updated_at=" + now + " WHERE installation_id=" + ph,
                        (installation_id,),
                    )
            finally:
                session.close()

    def apply(self, installation_id: str, agent_id: str) -> dict[str, Any] | None:
        settings = self.get(installation_id)
        if settings is None:
            return None

        ph = self.dialect.placeholder
        try:
            name = str(settings.get("requested_name") or "").strip()
            if name:
                with self.backend.transaction() as connection:
                    session = AlertSession(self.backend, connection)
                    try:
                        session.execute(
                            "UPDATE agents SET name=" + ph + " WHERE id=" + ph,
                            (name, str(agent_id)),
                        )
                    finally:
                        session.close()

            if settings.get("port_start") is not None:
                protocol = str(settings["port_protocol"])
                protocols = ("tcp", "udp") if protocol == "both" else (protocol,)
                AgentPortRepository(self.backend).set_ranges(
                    str(agent_id),
                    protocols=protocols,
                    start_port=int(settings["port_start"]),
                    end_port=int(settings["port_end"]),
                    force=False,
                )
        except Exception as exc:
            self._mark_result(installation_id, error=str(exc))
            raise

        self._mark_result(installation_id, error=None)
        return self.get(installation_id)
