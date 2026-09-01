#!/usr/bin/env python3
"""Controller-side state machine for typed remote Agent uninstall commands."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend

_METADATA_KEY = "admin_uninstall"
_FINAL_STATES = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


class AgentUninstallRepository:
    """Persist and exchange uninstall requests without arbitrary remote shell access."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self) -> None:
        self.backend.initialize()

    def _row(
        self,
        session: AlertSession,
        agent_id: str,
        *,
        for_update: bool = False,
    ):
        ph = self.dialect.placeholder
        lock_suffix = (
            " FOR UPDATE"
            if for_update and self.dialect.name in {"postgresql", "mysql"}
            else ""
        )
        row = session.execute(
            "SELECT id,node_id,metadata_json FROM agents "
            f"WHERE id={ph}{lock_suffix}",
            (agent_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Agent not found")
        return row

    def _store(self, session: AlertSession, agent_id: str, metadata: dict[str, Any]) -> None:
        ph = self.dialect.placeholder
        session.execute(
            f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
            (json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), default=str), agent_id),
        )

    def request(
        self,
        agent_id: str,
        *,
        mode: str,
        requested_by: str,
        confirmation: str,
    ) -> dict[str, Any]:
        self.initialize()
        agent_id = str(agent_id or "").strip()
        mode = str(mode or "").strip().lower()
        if not agent_id:
            raise ValueError("agent_id is required")
        if confirmation != agent_id:
            raise ValueError("confirmation must exactly match agent_id")
        if mode not in {"preserve-data", "purge"}:
            raise ValueError("mode must be preserve-data or purge")

        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id, for_update=True)
                instances = session.execute(
                    "SELECT id FROM instances WHERE node_id=" + ph + " ORDER BY id",
                    (str(row["node_id"]),),
                ).fetchall()
                if mode == "purge" and instances:
                    raise ValueError("purge is blocked while the Agent has registered instances")
                metadata = _metadata(row["metadata_json"])
                current = metadata.get(_METADATA_KEY)
                if isinstance(current, dict) and str(current.get("status") or "") not in _FINAL_STATES:
                    return dict(current)
                state = {
                    "request_id": "uninstall-" + secrets.token_hex(16),
                    "status": "queued",
                    "mode": mode,
                    "requested_at": _now(),
                    "requested_by": str(requested_by or "system"),
                }
                metadata[_METADATA_KEY] = state
                self._store(session, agent_id, metadata)
                return state
            finally:
                session.close()

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Return the typed command for the current uninstall phase.

        queued/delivered -> prepare
        accepted/commit-delivered -> commit

        Delivery is idempotent: an unacknowledged phase is redelivered with
        the same request_id, while the original delivery timestamp is kept.
        """
        self.initialize()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id, for_update=True)
                metadata = _metadata(row["metadata_json"])
                current = metadata.get(_METADATA_KEY)
                if not isinstance(current, dict):
                    return None
                status = str(current.get("status") or "")

                if status in {"queued", "delivered"}:
                    state = dict(current)
                    if status == "queued":
                        state["status"] = "delivered"
                        state["delivered_at"] = _now()
                        metadata[_METADATA_KEY] = state
                        self._store(session, agent_id, metadata)
                    return {
                        "kind": "AgentUninstallCommand",
                        "schema_version": 1,
                        "request_id": state["request_id"],
                        "action": "uninstall-agent",
                        "phase": "prepare",
                        "mode": state["mode"],
                    }

                if status in {"accepted", "commit-delivered"}:
                    state = dict(current)
                    if status == "accepted":
                        state["status"] = "commit-delivered"
                        state["commit_delivered_at"] = _now()
                        metadata[_METADATA_KEY] = state
                        self._store(session, agent_id, metadata)
                    return {
                        "kind": "AgentUninstallCommand",
                        "schema_version": 1,
                        "request_id": state["request_id"],
                        "action": "uninstall-agent",
                        "phase": "commit",
                        "mode": state["mode"],
                    }

                return None
            finally:
                session.close()

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        request_id = str(result.get("request_id") or "").strip()
        if not request_id:
            return None
        status = str(result.get("status") or "").strip().lower()
        if status not in {"accepted", "committed", "completed", "failed"}:
            return None

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id, for_update=True)
                metadata = _metadata(row["metadata_json"])
                current = metadata.get(_METADATA_KEY)
                if not isinstance(current, dict) or str(current.get("request_id")) != request_id:
                    return None
                current_status = str(current.get("status") or "")
                allowed = {
                    "accepted": {"delivered", "accepted"},
                    "committed": {"commit-delivered", "committed"},
                    "completed": {"commit-delivered", "committed", "completed"},
                    "failed": {"delivered", "accepted", "commit-delivered", "committed", "failed"},
                }
                if current_status not in allowed[status]:
                    return None
                state = dict(current)
                state["status"] = status
                stamp_key = {
                    "accepted": "accepted_at",
                    "committed": "committed_at",
                    "completed": "completed_at",
                    "failed": "completed_at",
                }[status]
                state[stamp_key] = str(result.get(stamp_key) or result.get("completed_at") or _now())
                if status in {"completed", "failed"}:
                    state["error"] = str(result.get("error") or "")[:1000] or None
                    state["host_cleanup"] = result.get("host_cleanup") if isinstance(result.get("host_cleanup"), dict) else None
                metadata[_METADATA_KEY] = state
                self._store(session, agent_id, metadata)
                return state
            finally:
                session.close()

    def state(self, agent_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                current = _metadata(row["metadata_json"]).get(_METADATA_KEY)
                return dict(current) if isinstance(current, dict) else None
            finally:
                session.close()
