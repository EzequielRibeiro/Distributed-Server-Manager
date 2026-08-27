#!/usr/bin/env python3
"""Controller-side persistent queue for per-instance Storage Pool migrations and source cleanup."""
from __future__ import annotations

from contextlib import contextmanager
import json
import re
from typing import Any, Iterator
import uuid

from agent_instance_provisioning_repository import _request_storage_reservation
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp
from storage_pool_placement import select_storage_pool
from universal_event_repository import UniversalEventRepository

OPERATION_TYPE = "storage_pool_migration"
CLEANUP_OPERATION_TYPE = "storage_pool_source_cleanup"
ACTIVE_STATES = {"queued", "delivered", "running"}
FINAL_STATES = {"completed", "failed"}
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return {}
    try:
        parsed = json.loads(str(value)) if value else {}
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _instance_storage_telemetry(metadata_json: Any, instance_id: str) -> dict[str, Any] | None:
    metadata = _json_object(metadata_json)
    values = metadata.get("instance_telemetry")
    if not isinstance(values, list):
        return None
    for item in values:
        if isinstance(item, dict) and str(item.get("instance_id") or "") == instance_id:
            return dict(item)
    return None


class InstanceStoragePoolMigrationRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.events = UniversalEventRepository(backend)

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

    def agent_for_instance(self, instance_id: str) -> str:
        instance_id = _token(instance_id, "instance_id")
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT agent_id FROM instances WHERE id={ph}", (instance_id,)).fetchone()
        if row is None:
            raise LookupError(instance_id)
        agent_id = str(row["agent_id"] or "").strip()
        if not agent_id:
            raise ValueError("Instance has no Agent")
        return agent_id

    def _publish(self, *, migration: dict[str, Any], event_type: str, severity: str = "info",
                 data: dict[str, Any] | None = None) -> None:
        request = migration.get("request") if isinstance(migration.get("request"), dict) else {}
        actor = str(request.get("requested_by") or "").strip() or None
        action = str(request.get("action") or "migrate").strip().lower()
        self.events.publish({
            "event_id": f"{migration['migration_id']}:{event_type.lower()}",
            "event_type": event_type,
            "occurred_at": utc_timestamp(),
            "source": "controller.storage-pool-cleanup" if action == "cleanup-source" else "controller.storage-pool-migration",
            "source_id": "controller.storage-pool-cleanup" if action == "cleanup-source" else "controller.storage-pool-migration",
            "severity": severity,
            "agent_id": str(request.get("agent_id") or "") or None,
            "instance_id": str(migration.get("instance_id") or request.get("instance_id") or "") or None,
            "correlation_id": migration["migration_id"],
            "actor_type": "user" if actor else "system",
            "actor_id": actor,
            "data": {
                "migration_id": migration["migration_id"],
                "source_migration_id": request.get("source_migration_id"),
                "source_storage_pool_id": request.get("source_storage_pool_id"),
                "target_storage_pool_id": request.get("target_storage_pool_id"),
                "required_storage_bytes": int(request.get("required_storage_bytes") or 0),
                "status": migration.get("status"),
                **dict(data or {}),
            },
        })

    def _active_reserved_bytes(self, session: AlertSession, agent_id: str) -> dict[str, int]:
        ph = self.dialect.placeholder
        totals: dict[str, int] = {}
        rows = session.execute(
            "SELECT request_json FROM agent_instance_provisioning "
            f"WHERE agent_id={ph} AND status IN ('queued','delivered','running')",
            (agent_id,),
        ).fetchall()
        for row in rows:
            pool_id, size = _request_storage_reservation(_json_object(row["request_json"]))
            if pool_id and size:
                totals[pool_id] = totals.get(pool_id, 0) + size

        rows = session.execute(
            "SELECT o.request_json FROM operations o JOIN instances i ON i.id=o.instance_id "
            f"WHERE o.operation_type={ph} AND i.agent_id={ph} "
            "AND o.status IN ('queued','delivered','running')",
            (OPERATION_TYPE, agent_id),
        ).fetchall()
        for row in rows:
            request = _json_object(row["request_json"])
            pool_id = str(request.get("target_storage_pool_id") or "").strip()
            try:
                size = max(0, int(request.get("required_storage_bytes") or 0))
            except (TypeError, ValueError):
                size = 0
            if pool_id and size:
                totals[pool_id] = totals.get(pool_id, 0) + size
        return totals

    def enqueue(self, *, instance_id: str, target_storage_pool_id: str,
                requested_by: str | None = None) -> dict[str, Any]:
        instance_id = _token(instance_id, "instance_id")
        target_storage_pool_id = _token(target_storage_pool_id, "target_storage_pool_id")
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            instance = session.execute(
                f"SELECT id,agent_id,node_id,status FROM instances WHERE id={ph}",
                (instance_id,),
            ).fetchone()
            if instance is None:
                raise ValueError("Instance not found")
            agent_id = str(instance["agent_id"] or "").strip()
            if not agent_id:
                raise ValueError("Instance has no Agent")
            lock_suffix = " FOR UPDATE" if self.dialect.name in {"postgresql", "mysql"} else ""
            agent = session.execute(
                f"SELECT status,metadata_json FROM agents WHERE id={ph}{lock_suffix}",
                (agent_id,),
            ).fetchone()
            if agent is None or str(agent["status"] or "").strip().lower() != "active":
                raise ValueError("Agent must be active")
            existing = session.execute(
                "SELECT o.id FROM operations o "
                f"WHERE o.instance_id={ph} AND o.operation_type={ph} "
                "AND o.status IN ('queued','delivered','running') ORDER BY o.created_at LIMIT 1",
                (instance_id, OPERATION_TYPE),
            ).fetchone()
            if existing is not None:
                return self.snapshot(str(existing["id"]))

            telemetry = _instance_storage_telemetry(agent["metadata_json"], instance_id)
            if telemetry is None:
                raise ValueError("Agent has not reported instance storage telemetry")
            source_pool_id = str(telemetry.get("storage_pool_id") or "").strip()
            if not source_pool_id:
                raise ValueError("Agent has not reported the instance Storage Pool")
            if source_pool_id == target_storage_pool_id:
                raise ValueError("Instance is already assigned to the target Storage Pool")
            try:
                required_bytes = int(telemetry.get("storage_used_bytes"))
            except (TypeError, ValueError) as exc:
                raise ValueError("Agent has not reported instance private storage size") from exc
            required_bytes = max(0, required_bytes)
            reservations = self._active_reserved_bytes(session, agent_id)
            decision = select_storage_pool(
                agent["metadata_json"],
                requested_pool_id=target_storage_pool_id,
                required_bytes=required_bytes,
                reserved_bytes_by_pool=reservations,
            )
            if decision is None:
                raise ValueError("Agent does not expose Storage Pools")

            migration_id = "storage-migration-" + uuid.uuid4().hex
            request = {
                "schema_version": 1,
                "kind": "CapivaraInstanceStoragePoolMigration",
                "action": "migrate",
                "migration_id": migration_id,
                "agent_id": agent_id,
                "instance_id": instance_id,
                "source_storage_pool_id": source_pool_id,
                "target_storage_pool_id": target_storage_pool_id,
                "required_storage_bytes": required_bytes,
                "requested_by": str(requested_by or "").strip() or None,
                "available_bytes_before": int(decision.get("available_bytes") or 0),
            }
            now = utc_timestamp()
            session.execute(
                "INSERT INTO operations(id,operation_type,status,node_id,instance_id,request_json,created_at) "
                f"VALUES ({self.dialect.parameters(7)})",
                (migration_id, OPERATION_TYPE, "queued", str(instance["node_id"] or "") or None,
                 instance_id, json.dumps(request, separators=(",", ":"), sort_keys=True), now),
            )

        state = self.snapshot(migration_id)
        self._publish(
            migration=state,
            event_type="INSTANCE_STORAGE_POOL_MIGRATION_REQUESTED",
            data={
                "available_bytes_before": request["available_bytes_before"],
                "available_bytes_after_reservation": max(0, request["available_bytes_before"] - required_bytes),
                "message": "Migração de Storage Pool solicitada e capacidade do destino reservada.",
            },
        )
        return state

    def cleanup_preview(self, source_migration_id: str) -> dict[str, Any]:
        source_migration_id = _token(source_migration_id, "source_migration_id")
        source = self.snapshot(source_migration_id)
        if source.get("operation_type") != OPERATION_TYPE:
            raise ValueError("cleanup source must be a Storage Pool migration")
        if str(source.get("status") or "").lower() != "completed":
            raise ValueError("Storage Pool migration must be completed before cleanup")
        request = source.get("request") if isinstance(source.get("request"), dict) else {}
        result = source.get("result") if isinstance(source.get("result"), dict) else {}
        if result.get("source_preserved") is False:
            raise ValueError("migration source is not preserved")
        instance_id = _token(source.get("instance_id") or request.get("instance_id"), "instance_id")
        agent_id = _token(request.get("agent_id"), "agent_id")
        source_pool = _token(request.get("source_storage_pool_id"), "source_storage_pool_id")
        target_pool = _token(request.get("target_storage_pool_id"), "target_storage_pool_id")
        ph = self.dialect.placeholder
        with self.session() as session:
            agent = session.execute(f"SELECT status,metadata_json FROM agents WHERE id={ph}", (agent_id,)).fetchone()
            if agent is None or str(agent["status"] or "").lower() != "active":
                raise ValueError("Agent must be active")
            telemetry = _instance_storage_telemetry(agent["metadata_json"], instance_id)
            if telemetry is None:
                raise ValueError("Agent has not reported current instance storage telemetry")
            current_pool = str(telemetry.get("storage_pool_id") or "").strip()
            if current_pool != target_pool:
                raise ValueError("Instance is not currently reported on the migration target Storage Pool")
            rows = session.execute(
                f"SELECT id,status,request_json FROM operations WHERE instance_id={ph} AND operation_type={ph} ORDER BY created_at DESC",
                (instance_id, CLEANUP_OPERATION_TYPE),
            ).fetchall()
        existing = None
        for row in rows:
            cleanup_request = _json_object(row["request_json"])
            if str(cleanup_request.get("source_migration_id") or "") == source_migration_id:
                existing = {"cleanup_id": str(row["id"]), "status": str(row["status"])}
                break
        return {
            "eligible": existing is None or existing["status"] == "failed",
            "source_migration_id": source_migration_id,
            "instance_id": instance_id,
            "agent_id": agent_id,
            "source_storage_pool_id": source_pool,
            "target_storage_pool_id": target_pool,
            "verified_files": result.get("verified_files"),
            "verified_bytes": result.get("verified_bytes"),
            "current_storage_pool_id": current_pool,
            "existing_cleanup": existing,
            "confirmation_required": source_migration_id,
            "warning": "A limpeza remove definitivamente a cópia preservada no Storage Pool de origem. Rollback para essa cópia deixa de ser possível.",
        }

    def enqueue_cleanup(self, *, source_migration_id: str, confirmation: str,
                        requested_by: str | None = None) -> dict[str, Any]:
        preview = self.cleanup_preview(source_migration_id)
        if str(confirmation or "").strip() != preview["confirmation_required"]:
            raise ValueError("cleanup confirmation must exactly match source_migration_id")
        existing = preview.get("existing_cleanup")
        if isinstance(existing, dict) and existing.get("status") in ACTIVE_STATES | {"completed"}:
            return self.snapshot(str(existing["cleanup_id"]))
        cleanup_id = "storage-cleanup-" + uuid.uuid4().hex
        source = self.snapshot(preview["source_migration_id"])
        source_request = source.get("request") if isinstance(source.get("request"), dict) else {}
        source_result = source.get("result") if isinstance(source.get("result"), dict) else {}
        request = {
            "schema_version": 1,
            "kind": "CapivaraInstanceStoragePoolSourceCleanup",
            "action": "cleanup-source",
            "migration_id": cleanup_id,
            "source_migration_id": preview["source_migration_id"],
            "agent_id": preview["agent_id"],
            "instance_id": preview["instance_id"],
            "source_storage_pool_id": preview["source_storage_pool_id"],
            "target_storage_pool_id": preview["target_storage_pool_id"],
            "required_storage_bytes": int(source_request.get("required_storage_bytes") or 0),
            "expected_verified_files": source_result.get("verified_files"),
            "expected_verified_bytes": source_result.get("verified_bytes"),
            "requested_by": str(requested_by or "").strip() or None,
        }
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            instance = session.execute(
                f"SELECT node_id FROM instances WHERE id={ph}", (preview["instance_id"],)
            ).fetchone()
            if instance is None:
                raise ValueError("Instance not found")
            active = session.execute(
                f"SELECT id FROM operations WHERE instance_id={ph} AND operation_type={ph} AND status IN ('queued','delivered','running') ORDER BY created_at LIMIT 1",
                (preview["instance_id"], CLEANUP_OPERATION_TYPE),
            ).fetchone()
            if active is not None:
                return self.snapshot(str(active["id"]))
            session.execute(
                "INSERT INTO operations(id,operation_type,status,node_id,instance_id,request_json,created_at) "
                f"VALUES ({self.dialect.parameters(7)})",
                (cleanup_id, CLEANUP_OPERATION_TYPE, "queued", str(instance["node_id"] or "") or None,
                 preview["instance_id"], json.dumps(request, separators=(",", ":"), sort_keys=True), utc_timestamp()),
            )
        state = self.snapshot(cleanup_id)
        self._publish(
            migration=state,
            event_type="INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_REQUESTED",
            data={"message": "Limpeza explícita da cópia preservada no Storage Pool de origem solicitada pelo administrador."},
        )
        return state

    def snapshot(self, migration_id: str) -> dict[str, Any]:
        migration_id = _token(migration_id, "migration_id")
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT * FROM operations WHERE id={ph} AND operation_type IN ({ph},{ph})",
                (migration_id, OPERATION_TYPE, CLEANUP_OPERATION_TYPE),
            ).fetchone()
        if row is None:
            raise KeyError(migration_id)
        value = dict(row)
        value["migration_id"] = value.pop("id")
        value["request"] = _json_object(value.pop("request_json", None))
        value["result"] = _json_object(value.pop("result_json", None)) or None
        return value

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        agent_id = str(agent_id or "").strip()
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT o.id FROM operations o JOIN instances i ON i.id=o.instance_id "
                f"WHERE i.agent_id={ph} AND o.operation_type IN ({ph},{ph}) "
                "AND o.status IN ('queued','delivered','running') ORDER BY o.created_at LIMIT 1",
                (agent_id, OPERATION_TYPE, CLEANUP_OPERATION_TYPE),
            ).fetchone()
        if row is None:
            return None
        state = self.snapshot(str(row["id"]))
        return dict(state["request"])

    def mark_delivered(self, migration_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE operations SET status=CASE WHEN status='queued' THEN 'delivered' ELSE status END "
                f"WHERE id={ph} AND operation_type IN ({ph},{ph}) AND status IN ('queued','delivered','running')",
                (migration_id, OPERATION_TYPE, CLEANUP_OPERATION_TYPE),
            )
        return self.snapshot(migration_id)

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        migration_id = str(result.get("migration_id") or "").strip()
        if not migration_id:
            return None
        current = self.snapshot(migration_id)
        request = current.get("request") or {}
        cleanup = str(request.get("action") or "").lower() == "cleanup-source"
        if str(request.get("agent_id") or "") != str(agent_id):
            raise PermissionError("storage pool operation belongs to another Agent")
        if str(result.get("instance_id") or "") != str(current.get("instance_id") or ""):
            raise ValueError("storage pool operation result instance_id mismatch")
        status = str(result.get("status") or "").strip().lower()
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid storage pool operation result status")
        try:
            progress = max(0, min(100, int(result.get("progress") or 0)))
        except (TypeError, ValueError):
            progress = 0
        step = str(result.get("current_step") or status).strip()[:128]
        error = str(result.get("error") or "").strip()[:2000] or None
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        now = utc_timestamp()
        ph = self.dialect.placeholder
        op_type = CLEANUP_OPERATION_TYPE if cleanup else OPERATION_TYPE
        with self.session(transaction=True) as session:
            if status == "running":
                session.execute(
                    "UPDATE operations SET status='running',result_json=" + ph + ","
                    "started_at=CASE WHEN started_at IS NULL THEN " + ph + " ELSE started_at END "
                    f"WHERE id={ph} AND operation_type={ph} AND status NOT IN ('completed','failed')",
                    (payload, now, migration_id, op_type),
                )
            else:
                session.execute(
                    "UPDATE operations SET status=" + ph + ",result_json=" + ph + ",error_code=" + ph + ",completed_at=" + ph + " "
                    f"WHERE id={ph} AND operation_type={ph} AND status NOT IN ('completed','failed')",
                    (status, payload, error, now, migration_id, op_type),
                )
        state = self.snapshot(migration_id)
        if cleanup:
            if status == "running":
                event_type = "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_STARTED" if progress <= 1 else "INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_PROGRESS"
                self._publish(migration=state, event_type=event_type, data={"progress": progress, "current_step": step})
            elif status == "completed":
                self._publish(
                    migration=state,
                    event_type="INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_COMPLETED",
                    data={
                        "progress": 100,
                        "removed_files": result.get("removed_files"),
                        "removed_bytes": result.get("removed_bytes"),
                        "message": "Cópia preservada no Storage Pool de origem removida após validação do destino.",
                    },
                )
            else:
                self._publish(
                    migration=state,
                    event_type="INSTANCE_STORAGE_POOL_SOURCE_CLEANUP_FAILED",
                    severity="critical",
                    data={"progress": 100, "error": error},
                )
            return state

        if status == "running":
            event_type = "INSTANCE_STORAGE_POOL_MIGRATION_STARTED" if progress <= 1 else "INSTANCE_STORAGE_POOL_MIGRATION_PROGRESS"
            self._publish(migration=state, event_type=event_type, data={"progress": progress, "current_step": step})
        elif status == "completed":
            self._publish(
                migration=state,
                event_type="INSTANCE_STORAGE_POOL_MIGRATION_COMPLETED",
                data={
                    "progress": 100,
                    "verified_files": result.get("verified_files"),
                    "verified_bytes": result.get("verified_bytes"),
                    "source_preserved": bool(result.get("source_preserved", True)),
                    "message": "Migração de Storage Pool concluída; a origem foi preservada.",
                },
            )
        else:
            self._publish(
                migration=state,
                event_type="INSTANCE_STORAGE_POOL_MIGRATION_FAILED",
                severity="critical",
                data={"progress": 100, "error": error, "rollback_error": result.get("rollback_error")},
            )
        if status in FINAL_STATES:
            self._publish(
                migration=state,
                event_type="INSTANCE_STORAGE_POOL_MIGRATION_CAPACITY_RELEASED",
                data={
                    "released_bytes": int(request.get("required_storage_bytes") or 0),
                    "final_status": status,
                    "message": "Reserva lógica de capacidade da migração foi liberada.",
                },
            )
        return state


__all__ = [
    "ACTIVE_STATES",
    "CLEANUP_OPERATION_TYPE",
    "FINAL_STATES",
    "OPERATION_TYPE",
    "InstanceStoragePoolMigrationRepository",
]
