#!/usr/bin/env python3
"""Persistence and rollout coordination for remote Agent updates."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp

VALID_CHANNELS = {"stable", "beta", "local/manual"}
UPDATE_STATES = {"idle", "planned", "updating", "verifying", "completed", "failed"}


class AgentUpdateRepository:
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

    def _ensure(self, session: AlertSession, agent_id: str) -> None:
        ph = self.dialect.placeholder
        exists = session.execute(
            f"SELECT 1 FROM agent_update_state WHERE agent_id={ph}", (agent_id,)
        ).fetchone()
        if exists is None:
            session.execute(
                "INSERT INTO agent_update_state(agent_id,update_channel,update_status,updated_at) "
                f"VALUES ({self.dialect.parameters(4)})",
                (agent_id, "stable", "idle", utc_timestamp()),
            )

    def report_version(self, agent_id: str, installed_version: str | None) -> dict[str, Any]:
        ph = self.dialect.placeholder
        version = str(installed_version or "").strip() or None
        with self.session(transaction=True) as session:
            self._ensure(session, agent_id)
            session.execute(
                f"UPDATE agent_update_state SET installed_version={ph},updated_at={ph} WHERE agent_id={ph}",
                (version, utc_timestamp(), agent_id),
            )
        return self.snapshot(agent_id)

    def set_available_version(self, agent_id: str, version: str | None) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            self._ensure(session, agent_id)
            session.execute(
                f"UPDATE agent_update_state SET available_version={ph},updated_at={ph} WHERE agent_id={ph}",
                (str(version or "").strip() or None, utc_timestamp(), agent_id),
            )
        return self.snapshot(agent_id)

    def set_channel(self, agent_id: str, channel: str) -> dict[str, Any]:
        channel = str(channel or "").strip().lower()
        if channel not in VALID_CHANNELS:
            raise ValueError("invalid update channel")
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            self._ensure(session, agent_id)
            session.execute(
                f"UPDATE agent_update_state SET update_channel={ph},updated_at={ph} WHERE agent_id={ph}",
                (channel, utc_timestamp(), agent_id),
            )
        return self.snapshot(agent_id)

    def snapshot(self, agent_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT * FROM agent_update_state WHERE agent_id={ph}", (agent_id,)
            ).fetchone()
        if row is None:
            return {
                "agent_id": agent_id,
                "installed_version": None,
                "available_version": None,
                "update_channel": "stable",
                "desired_version": None,
                "update_status": "idle",
                "rollout_id": None,
                "batch_number": None,
                "batch_position": None,
                "requested_at": None,
                "last_update": None,
                "last_error": None,
            }
        return dict(row)

    def create_rollout(
        self,
        agent_ids: list[str],
        *,
        desired_version: str,
        channel: str = "stable",
        batch_size: int = 1,
    ) -> dict[str, Any]:
        channel = str(channel).strip().lower()
        if channel not in VALID_CHANNELS:
            raise ValueError("invalid update channel")
        desired_version = str(desired_version or "").strip().lstrip("v")
        if not desired_version:
            raise ValueError("desired_version is required")
        batch_size = int(batch_size)
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        clean_ids = list(dict.fromkeys(str(item).strip() for item in agent_ids if str(item).strip()))
        if not clean_ids:
            raise ValueError("at least one Agent is required")

        rollout_id = "rollout-" + uuid.uuid4().hex
        ph = self.dialect.placeholder
        now = utc_timestamp()
        with self.session(transaction=True) as session:
            for position, agent_id in enumerate(clean_ids):
                self._ensure(session, agent_id)
                batch_number = position // batch_size + 1
                session.execute(
                    "UPDATE agent_update_state SET "
                    f"desired_version={ph},available_version={ph},update_channel={ph},"
                    f"update_status={ph},rollout_id={ph},batch_number={ph},batch_position={ph},"
                    f"requested_at={ph},last_error={ph},updated_at={ph} WHERE agent_id={ph}",
                    (
                        desired_version, desired_version, channel, "planned", rollout_id,
                        batch_number, position + 1, now, None, now, agent_id,
                    ),
                )
        return {
            "rollout_id": rollout_id,
            "desired_version": desired_version,
            "channel": channel,
            "batch_size": batch_size,
            "agents": clean_ids,
            "total_batches": (len(clean_ids) + batch_size - 1) // batch_size,
        }

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        state = self.snapshot(agent_id)
        if state.get("update_status") not in {"planned", "updating", "verifying"}:
            return None
        rollout_id = state.get("rollout_id")
        batch = state.get("batch_number")
        if not rollout_id or batch is None:
            return None
        ph = self.dialect.placeholder
        with self.session() as session:
            blockers = session.execute(
                "SELECT update_status FROM agent_update_state "
                f"WHERE rollout_id={ph} AND batch_number<{ph}",
                (rollout_id, batch),
            ).fetchall()
        if any(str(row["update_status"]) != "completed" for row in blockers):
            return None
        return {
            "rollout_id": rollout_id,
            "desired_version": state.get("desired_version"),
            "channel": state.get("update_channel"),
            "batch_number": batch,
        }

    def mark_updating(self, agent_id: str) -> dict[str, Any]:
        return self._mark(agent_id, "updating")

    def mark_verifying(self, agent_id: str) -> dict[str, Any]:
        return self._mark(agent_id, "verifying")

    def mark_failed(self, agent_id: str, error: str) -> dict[str, Any]:
        return self._mark(agent_id, "failed", error=error)

    def reconcile_after_heartbeat(
        self,
        agent_id: str,
        installed_version: str | None,
        health_status: str,
    ) -> dict[str, Any]:
        state = self.report_version(agent_id, installed_version)
        desired = str(state.get("desired_version") or "").strip().lstrip("v")
        installed = str(installed_version or "").strip().lstrip("v")
        current_status = str(state.get("update_status") or "idle")
        if (
            current_status in {"planned", "updating", "verifying"}
            and desired
            and installed == desired
            and str(health_status).lower() == "online"
        ):
            return self._mark(agent_id, "completed", completed=True)
        if current_status == "updating" and installed != desired:
            return self._mark(agent_id, "verifying")
        return self.snapshot(agent_id)

    def _mark(
        self,
        agent_id: str,
        status: str,
        *,
        error: str | None = None,
        completed: bool = False,
    ) -> dict[str, Any]:
        if status not in UPDATE_STATES:
            raise ValueError("invalid update status")
        ph = self.dialect.placeholder
        now = utc_timestamp()
        with self.session(transaction=True) as session:
            self._ensure(session, agent_id)
            if completed:
                session.execute(
                    "UPDATE agent_update_state SET "
                    f"update_status={ph},last_error={ph},last_update={ph},updated_at={ph} WHERE agent_id={ph}",
                    (status, error, now, now, agent_id),
                )
            else:
                session.execute(
                    "UPDATE agent_update_state SET "
                    f"update_status={ph},last_error={ph},updated_at={ph} WHERE agent_id={ph}",
                    (status, error, now, agent_id),
                )
        return self.snapshot(agent_id)


__all__ = ["AgentUpdateRepository", "VALID_CHANNELS"]
