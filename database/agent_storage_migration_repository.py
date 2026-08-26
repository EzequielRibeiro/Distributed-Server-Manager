#!/usr/bin/env python3
"""Controller-side durable state for Agent instance storage migration."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class AgentStorageMigrationRepository:
    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    @staticmethod
    def _metadata(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        try:
            value = json.loads(str(raw or "{}"))
        except Exception:
            value = {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def _row(self, session: AlertSession, agent_id: str):
        ph = self.dialect.placeholder
        row = session.execute(f"SELECT id,metadata_json FROM agents WHERE id={ph}", (agent_id,)).fetchone()
        if row is None:
            raise LookupError("Agent not found")
        return row

    def request(self, agent_id: str, *, target_root: str, actor: str) -> dict[str, Any]:
        target_root = str(target_root or "").strip()
        if not target_root.startswith("/") or target_root == "/":
            raise ValueError("target_root must be an absolute non-root path")
        migration_id = "storage-" + secrets.token_hex(16)
        state = {
            "migration_id": migration_id,
            "status": "queued",
            "target_root": target_root,
            "requested_at": _now(),
            "requested_by": str(actor or "system"),
        }
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                current = metadata.get("admin_storage_migration")
                if isinstance(current, dict) and str(current.get("status") or "") in {"queued", "delivered", "running"}:
                    raise RuntimeError("storage migration already in progress")
                metadata["admin_storage_migration"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
            finally:
                session.close()
        return state

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                state = metadata.get("admin_storage_migration")
                if not isinstance(state, dict) or state.get("status") != "queued":
                    return None
                state = dict(state)
                state["status"] = "delivered"
                state["delivered_at"] = _now()
                metadata["admin_storage_migration"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
                return {
                    "migration_id": state["migration_id"],
                    "action": "migrate-instance-storage",
                    "target_root": state["target_root"],
                }
            finally:
                session.close()

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        migration_id = str(result.get("migration_id") or "").strip()
        if not migration_id:
            return None
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                metadata = self._metadata(row["metadata_json"])
                current = metadata.get("admin_storage_migration")
                if not isinstance(current, dict) or str(current.get("migration_id") or "") != migration_id:
                    return None
                state = dict(current)
                state.update({
                    "status": str(result.get("status") or "failed"),
                    "completed_at": _now(),
                    "source_root": result.get("source_root"),
                    "target_root": result.get("target_root") or state.get("target_root"),
                    "instances": result.get("instances") or result.get("copied_instances") or [],
                    "source_preserved": bool(result.get("source_preserved")),
                    "error": result.get("error"),
                })
                metadata["admin_storage_migration"] = state
                session.execute(
                    f"UPDATE agents SET metadata_json={ph},updated_at=CURRENT_TIMESTAMP WHERE id={ph}",
                    (self._json(metadata), agent_id),
                )
                return state
            finally:
                session.close()

    def latest(self, agent_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = self._row(session, agent_id)
                state = self._metadata(row["metadata_json"]).get("admin_storage_migration")
                return dict(state) if isinstance(state, dict) else None
            finally:
                session.close()


__all__ = ["AgentStorageMigrationRepository"]
