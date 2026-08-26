#!/usr/bin/env python3
"""Controller-side persistence and delivery for instance provisioning."""
from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp
from storage_pool_placement import select_storage_pool
from universal_event_repository import UniversalEventRepository

ACTIVE_STATES = {"queued", "delivered", "running"}
FINAL_STATES = {"completed", "failed"}
VALID_STATES = {*ACTIVE_STATES, *FINAL_STATES}
VALID_DESIRED_STATES = {"running", "stopped"}


class AgentInstanceProvisioningRepository:
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

    def _publish_event(self, *, event_id: str, event_type: str, severity: str,
                       provisioning: dict[str, Any], data: dict[str, Any] | None = None) -> None:
        requested_by = str(provisioning.get("requested_by") or "").strip() or None
        payload = {
            "provisioning_id": str(provisioning.get("provisioning_id") or ""),
            "status": str(provisioning.get("status") or ""),
            "current_step": str(provisioning.get("current_step") or ""),
            "progress": int(provisioning.get("progress") or 0),
            "environment_id": str(provisioning.get("environment_id") or ""),
            "selector": str(provisioning.get("selector") or ""),
            **dict(data or {}),
        }
        self.events.publish({
            "event_id": event_id, "event_type": event_type, "occurred_at": utc_timestamp(),
            "source": "controller.provisioning", "source_id": "controller.provisioning", "severity": severity,
            "agent_id": str(provisioning.get("agent_id") or "") or None,
            "instance_id": str(provisioning.get("instance_id") or "") or None,
            "correlation_id": str(provisioning.get("provisioning_id") or "") or None,
            "actor_type": "user" if requested_by else "system", "actor_id": requested_by, "data": payload,
        })

    @staticmethod
    def _steam_auth_required(error: str | None, result: dict[str, Any]) -> bool:
        if bool(result.get("steam_auth_required")):
            return True
        text = str(error or "").lower()
        return any(token in text for token in ("steam guard", "steam auth", "steam login", "steam authentication"))

    def enqueue(self, *, agent_id: str, instance_id: str, environment_id: str, selector: str,
                selection: dict[str, Any], configuration: dict[str, Any] | None = None,
                desired_state: str = "stopped", requested_by: str | None = None,
                storage_pool_id: str | None = None, storage_class: str | None = None,
                required_storage_bytes: int | None = None) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip()
        instance_id = str(instance_id or "").strip()
        environment_id = str(environment_id or "").strip()
        selector = str(selector or "").strip()
        desired_state = str(desired_state or "stopped").strip().lower()
        if not agent_id or not instance_id or not environment_id or not selector:
            raise ValueError("agent_id, instance_id, environment_id and selector are required")
        if desired_state not in VALID_DESIRED_STATES:
            raise ValueError("invalid desired_state")
        if not isinstance(selection, dict) or not selection:
            raise ValueError("runtime selection is required")
        if configuration is not None and not isinstance(configuration, dict):
            raise ValueError("configuration must be an object")
        if required_storage_bytes is not None:
            try:
                required_storage_bytes = int(required_storage_bytes)
            except (TypeError, ValueError) as exc:
                raise ValueError("required_storage_bytes must be an integer") from exc
            if required_storage_bytes < 0:
                raise ValueError("required_storage_bytes cannot be negative")

        ph = self.dialect.placeholder
        storage_decision: dict[str, Any] | None = None
        with self.session(transaction=True) as session:
            agent = session.execute(
                f"SELECT status,metadata_json FROM agents WHERE id={ph}", (agent_id,)
            ).fetchone()
            if agent is None or str(agent["status"] or "").strip().lower() != "active":
                raise ValueError("Agent must be active")
            storage_decision = select_storage_pool(
                agent["metadata_json"], requested_pool_id=storage_pool_id,
                preferred_storage_class=storage_class, required_bytes=required_storage_bytes,
            )
            instance = session.execute(
                f"SELECT id,agent_id,node_id,game_id,runtime_id FROM instances WHERE id={ph}", (instance_id,)
            ).fetchone()
            if instance is None:
                raise ValueError("Instance not found")
            if str(instance["agent_id"] or "") != agent_id:
                raise PermissionError("Instance belongs to another Agent")
            existing = session.execute(
                "SELECT provisioning_id FROM agent_instance_provisioning "
                f"WHERE instance_id={ph} AND status IN ('queued','delivered','running') "
                "ORDER BY created_at ASC LIMIT 1", (instance_id,),
            ).fetchone()
            if existing is not None:
                return self.snapshot(str(existing["provisioning_id"]))
            rows = session.execute(
                "SELECT name,protocol,port,bind_address FROM instance_ports "
                f"WHERE instance_id={ph} ORDER BY name,protocol,port", (instance_id,),
            ).fetchall()
            ports = {str(row["name"]): {"port": int(row["port"]), "protocol": str(row["protocol"]),
                     "bind_address": str(row["bind_address"] or "0.0.0.0")} for row in rows}
            if not ports:
                raise ValueError("Instance has no reserved ports")
            provisioning_id = "instance-provision-" + uuid.uuid4().hex
            instance_request = {
                "instance_id": instance_id, "agent_id": agent_id, "game_id": str(instance["game_id"] or ""),
                "environment_id": environment_id, "runtime_id": str(instance["runtime_id"] or instance_id),
                "desired_state": desired_state,
            }
            if storage_decision is not None:
                instance_request["storage_pool_id"] = storage_decision["storage_pool_id"]
            request = {
                "schema_version": 1, "kind": "CapivaraInstanceProvisioningRequest",
                "provisioning_id": provisioning_id, "agent_id": agent_id, "instance_id": instance_id,
                "environment_id": environment_id, "selector": selector, "desired_state": desired_state,
                "instance": instance_request, "content": {"action": "ensure", "selection": selection},
                "ports": ports, "configuration": dict(configuration or {}),
            }
            now = utc_timestamp()
            session.execute(
                "INSERT INTO agent_instance_provisioning("
                "provisioning_id,agent_id,instance_id,environment_id,selector,request_json,"
                "status,current_step,progress,requested_by,created_at,updated_at) "
                f"VALUES ({self.dialect.parameters(12)})",
                (provisioning_id, agent_id, instance_id, environment_id, selector,
                 json.dumps(request, separators=(",", ":"), sort_keys=True), "queued", "queued", 0,
                 str(requested_by or "").strip() or None, now, now),
            )

        state = self.snapshot(provisioning_id)
        if storage_decision is not None:
            self._publish_event(
                event_id=f"{provisioning_id}:storage-pool-selected",
                event_type="INSTANCE_STORAGE_POOL_SELECTED", severity="info", provisioning=state,
                data={
                    "storage_pool_id": storage_decision["storage_pool_id"],
                    "storage_class": storage_decision["storage_class"],
                    "usable_bytes": storage_decision["usable_bytes"],
                    "priority": storage_decision["priority"],
                    "selection_source": storage_decision["source"],
                    "selection_reason": storage_decision["reason"],
                    "message": "Storage Pool selecionado para a instância antes do provisionamento.",
                },
            )
        self._publish_event(
            event_id=f"{provisioning_id}:queued", event_type="INSTANCE_PROVISION_QUEUED", severity="info",
            provisioning=state, data={"message": "Provisionamento da instância foi enfileirado para o Agent."},
        )
        return state

    def snapshot(self, provisioning_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT * FROM agent_instance_provisioning WHERE provisioning_id={ph}",
                                  (provisioning_id,)).fetchone()
        if row is None:
            raise KeyError(provisioning_id)
        result = dict(row)
        for source, target in (("request_json", "request"), ("result_json", "result")):
            raw = result.pop(source, None)
            try:
                result[target] = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                result[target] = None
        return result

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT provisioning_id FROM agent_instance_provisioning "
                f"WHERE agent_id={ph} AND status IN ('queued','delivered','running') "
                "ORDER BY created_at ASC LIMIT 1", (agent_id,),
            ).fetchone()
        if row is None:
            return None
        state = self.snapshot(str(row["provisioning_id"]))
        request = dict(state.get("request") or {})
        request["provisioning_id"] = state["provisioning_id"]
        return request

    def mark_delivered(self, provisioning_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        now = utc_timestamp()
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE agent_instance_provisioning SET "
                "status=CASE WHEN status='queued' THEN 'delivered' ELSE status END,"
                f"delivered_at=CASE WHEN delivered_at IS NULL THEN {ph} ELSE delivered_at END,"
                f"updated_at={ph} WHERE provisioning_id={ph} AND status IN ('queued','delivered','running')",
                (now, now, provisioning_id),
            )
        return self.snapshot(provisioning_id)

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        provisioning_id = str(result.get("provisioning_id") or "").strip()
        if not provisioning_id:
            return None
        current = self.snapshot(provisioning_id)
        if str(current.get("agent_id") or "") != str(agent_id):
            raise PermissionError("provisioning operation belongs to another Agent")
        if str(result.get("instance_id") or "") != str(current.get("instance_id") or ""):
            raise ValueError("provisioning result instance_id mismatch")
        status = str(result.get("status") or "").strip().lower()
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid provisioning result status")
        try:
            progress = int(result.get("progress", current.get("progress", 0)))
        except (TypeError, ValueError):
            progress = int(current.get("progress", 0) or 0)
        progress = 100 if status in FINAL_STATES else max(0, min(progress, 99))
        current_step = str(result.get("current_step") or current.get("current_step") or status).strip()[:128]
        error = str(result.get("error") or "").strip()[:2000] or None
        now = utc_timestamp()
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            if status == "running":
                session.execute(
                    "UPDATE agent_instance_provisioning SET "
                    f"status={ph},current_step={ph},progress={ph},result_json={ph},last_error={ph},"
                    f"started_at=CASE WHEN started_at IS NULL THEN {ph} ELSE started_at END,updated_at={ph} "
                    f"WHERE provisioning_id={ph} AND status NOT IN ('completed','failed')",
                    (status, current_step, progress, payload, error, now, now, provisioning_id),
                )
            else:
                session.execute(
                    "UPDATE agent_instance_provisioning SET "
                    f"status={ph},current_step={ph},progress={ph},result_json={ph},last_error={ph},"
                    f"completed_at={ph},updated_at={ph} WHERE provisioning_id={ph} AND status NOT IN ('completed','failed')",
                    (status, current_step, progress, payload, error, now, now, provisioning_id),
                )

        state = self.snapshot(provisioning_id)
        if status == "running":
            self._publish_event(event_id=f"{provisioning_id}:running:{current_step}:{progress}",
                event_type="INSTANCE_PROVISION_STARTED", severity="info", provisioning=state,
                data={"message": "O Agent iniciou o provisionamento da instância."})
        elif status == "completed":
            self._publish_event(event_id=f"{provisioning_id}:completed", event_type="INSTANCE_PROVISION_COMPLETED",
                severity="info", provisioning=state,
                data={"message": "Provisionamento da instância concluído com sucesso."})
        else:
            self._publish_event(event_id=f"{provisioning_id}:failed", event_type="INSTANCE_PROVISION_FAILED",
                severity="critical", provisioning=state,
                data={"message": "Falha durante o provisionamento da instância.", "error": error})
            if self._steam_auth_required(error, result):
                self._publish_event(event_id=f"{provisioning_id}:steam-auth-required",
                    event_type="STEAM_AUTH_REQUIRED", severity="critical", provisioning=state,
                    data={"message": "Autenticação Steam necessária no Agent para continuar o provisionamento.",
                          "error": error})
        return state


__all__ = ["ACTIVE_STATES", "FINAL_STATES", "VALID_STATES", "AgentInstanceProvisioningRepository"]
