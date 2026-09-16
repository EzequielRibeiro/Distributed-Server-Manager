#!/usr/bin/env python3
"""M5 bridge for restart-required managed configuration.

Server settings are materialized by the Agent through the Universal Configuration
Platform.  M5 only decides whether a successful stop/start is still required to
activate the latest materialized revision.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from configuration_repository import ConfigurationRepository

SERVER_SETTINGS_NAMESPACE = "capivara.instance.server-settings"


def _parse_time(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _requires_restart(configuration: dict[str, Any] | None) -> bool:
    value = dict((configuration or {}).get("value") or {})
    declaration = value.get("declaration") if isinstance(value.get("declaration"), dict) else {}
    return bool(declaration.get("restart_required", True))


class MaintenanceConfigurationCoordinator:
    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.configuration = ConfigurationRepository(backend)
        self.configuration.initialize()

    @property
    def ph(self) -> str:
        return self.dialect.placeholder

    def _instance_agent(self, instance_id: str) -> str | None:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT agent_id FROM instances WHERE id={self.ph}",
                    (str(instance_id),),
                ).fetchone()
            finally:
                session.close()
        if row is None:
            return None
        value = str(row["agent_id"] or "").strip()
        return value or None

    def _last_successful_restart(self, instance_id: str) -> datetime | None:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT completed_at FROM instance_maintenance_runs "
                    f"WHERE instance_id={self.ph} AND status='completed' AND completed_at IS NOT NULL "
                    "ORDER BY completed_at DESC LIMIT 1",
                    (str(instance_id),),
                ).fetchone()
            finally:
                session.close()
        return _parse_time(row["completed_at"]) if row is not None else None

    def _resolved(self, agent_id: str, instance_id: str) -> dict[str, Any] | None:
        return next(
            (
                dict(item)
                for item in self.configuration.resolve_for_instance(agent_id, instance_id)
                if str(item.get("namespace") or "") == SERVER_SETTINGS_NAMESPACE
            ),
            None,
        )

    def _agent_state(self, agent_id: str, instance_id: str) -> dict[str, Any] | None:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT desired_revision,applied_revision,desired_checksum,applied_checksum,status,last_error "
                    "FROM agent_configuration_state "
                    f"WHERE agent_id={self.ph} AND target_type='instance' AND target_id={self.ph} AND namespace={self.ph}",
                    (str(agent_id), str(instance_id), SERVER_SETTINGS_NAMESPACE),
                ).fetchone()
            finally:
                session.close()
        return dict(row) if row is not None else None

    def discover(self, instance_id: str) -> list[dict[str, Any]]:
        iid = str(instance_id)
        raw = self.configuration.get(
            scope_type="instance",
            scope_id=iid,
            namespace=SERVER_SETTINGS_NAMESPACE,
        )
        if raw is None or not _requires_restart(raw):
            return []
        changed_at = _parse_time(raw.get("updated_at"))
        activated_at = self._last_successful_restart(iid)
        if changed_at is not None and activated_at is not None and activated_at >= changed_at:
            return []
        agent_id = self._instance_agent(iid)
        if not agent_id:
            return []
        resolved = self._resolved(agent_id, iid)
        if resolved is None:
            return []
        revision = str(resolved.get("revision") or "").strip()
        if not revision:
            return []
        return [{
            "kind": "configuration",
            "ref": SERVER_SETTINGS_NAMESPACE,
            "available_version": revision,
            "status": "pending",
        }]

    def alignment(self, instance_id: str, pending_work: list[dict[str, Any]]) -> dict[str, Any]:
        iid = str(instance_id)
        works = [dict(item) for item in pending_work]
        indexes = [i for i, item in enumerate(works) if item.get("kind") == "configuration"]
        if not indexes:
            return {"ready": True, "pending": [], "failed": [], "aligned": [], "work": works}
        agent_id = self._instance_agent(iid)
        if not agent_id:
            return {"ready": False, "pending": [SERVER_SETTINGS_NAMESPACE], "failed": [], "aligned": [], "work": works}
        raw = self.configuration.get(
            scope_type="instance",
            scope_id=iid,
            namespace=SERVER_SETTINGS_NAMESPACE,
        )
        resolved = self._resolved(agent_id, iid)
        state = self._agent_state(agent_id, iid)
        pending: list[str] = []
        failed: list[dict[str, Any]] = []
        aligned: list[str] = []
        for index in indexes:
            item = works[index]
            if raw is None or not _requires_restart(raw) or resolved is None:
                item["status"] = "skipped"
                continue
            revision = str(resolved.get("revision") or "").strip()
            checksum = str(resolved.get("checksum") or "").strip()
            item["available_version"] = revision
            status = str((state or {}).get("status") or "").lower()
            desired_revision = str((state or {}).get("desired_revision") or "")
            applied_revision = str((state or {}).get("applied_revision") or "")
            applied_checksum = str((state or {}).get("applied_checksum") or "")
            if status == "failed" and desired_revision == revision:
                item["status"] = "failed"
                item["error"] = str((state or {}).get("last_error") or "configuration reconciliation failed")[:500]
                failed.append(item)
            elif status == "applied" and applied_revision == revision and applied_checksum == checksum:
                item["status"] = "aligned"
                item.pop("error", None)
                aligned.append(str(item.get("ref") or SERVER_SETTINGS_NAMESPACE))
            else:
                item["status"] = "pending"
                item.pop("error", None)
                pending.append(str(item.get("ref") or SERVER_SETTINGS_NAMESPACE))
            works[index] = item
        return {
            "ready": not pending and not failed,
            "pending": pending,
            "failed": failed,
            "aligned": aligned,
            "work": works,
        }


__all__ = ["MaintenanceConfigurationCoordinator", "SERVER_SETTINGS_NAMESPACE"]
