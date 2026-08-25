#!/usr/bin/env python3
"""Persistence for Customer Instance Workspace v2."""
from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Iterator
import uuid

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_instance_policy import INSTANCE_PERMISSIONS, effective_permissions

FINAL_CONSOLE_STATES = {"completed", "failed"}
CONTRACT_CHANGE_STATES = {
    "requested", "pending_billing", "paid", "approved", "applying",
    "applied", "failed", "cancelled",
}


class InstanceWorkspaceRepository:
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

    def _bool(self, value: bool) -> Any:
        return bool(value) if self.backend.name == "postgresql" else int(bool(value))

    @staticmethod
    def _decode_json(value: Any, default):
        if isinstance(value, (dict, list)):
            return value
        if value in {None, ""}:
            return default
        try:
            return json.loads(str(value))
        except (TypeError, ValueError):
            return default

    def instance_context(self, instance_id: str) -> dict[str, Any]:
        instance_id = str(instance_id or "").strip()
        if not instance_id:
            raise ValueError("instance_id is required")
        self.initialize(); ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT i.*,ic.contract_id,c.status AS contract_status,c.metadata_json AS contract_metadata_json "
                "FROM instances i LEFT JOIN instance_contracts ic ON ic.instance_id=i.id "
                "LEFT JOIN service_contracts c ON c.id=ic.contract_id "
                f"WHERE i.id={ph}",
                (instance_id,),
            ).fetchone()
        if row is None:
            raise KeyError(instance_id)
        result = dict(row)
        result["contract_metadata"] = self._decode_json(result.pop("contract_metadata_json", None), {})
        result["instance_metadata"] = self._decode_json(result.get("metadata_json"), {})
        return result

    # ------------------------------------------------------------------ policy
    def workspace_policy(self, instance_id: str) -> dict[str, Any]:
        context = self.instance_context(instance_id)
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT * FROM instance_workspace_policy WHERE instance_id={ph}",
                (instance_id,),
            ).fetchone()
        if row is None:
            metadata = context.get("contract_metadata") or {}
            resources = metadata.get("resources") if isinstance(metadata.get("resources"), dict) else {}
            entitlements = metadata.get("entitlements") if isinstance(metadata.get("entitlements"), dict) else {}
            return {
                "instance_id": instance_id,
                "resource_profile_id": metadata.get("resource_profile_id") or metadata.get("profile_id"),
                "storage_limit_bytes": resources.get("storage_bytes"),
                "content_mode": "modified" if any(bool(entitlements.get(x)) for x in ("mods", "plugins", "workshop")) else "standard",
                "mods_allowed": bool(entitlements.get("mods")),
                "plugins_allowed": bool(entitlements.get("plugins")),
                "workshop_allowed": bool(entitlements.get("workshop")),
                "external_upload_allowed": bool(entitlements.get("external_upload", True)),
                "custom_runtime_allowed": bool(entitlements.get("custom_runtime", False)),
                "startup": {},
            }
        result = dict(row)
        result["startup"] = self._decode_json(result.pop("startup_json", None), {})
        for key in ("mods_allowed", "plugins_allowed", "workshop_allowed", "external_upload_allowed", "custom_runtime_allowed"):
            result[key] = bool(result.get(key))
        return result

    def save_workspace_policy(self, instance_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        self.instance_context(instance_id)
        policy = policy if isinstance(policy, dict) else {}
        values = {
            "resource_profile_id": str(policy.get("resource_profile_id") or "").strip() or None,
            "storage_limit_bytes": int(policy["storage_limit_bytes"]) if policy.get("storage_limit_bytes") is not None else None,
            "content_mode": "modified" if str(policy.get("content_mode") or "standard").lower() == "modified" else "standard",
            "mods_allowed": self._bool(bool(policy.get("mods_allowed"))),
            "plugins_allowed": self._bool(bool(policy.get("plugins_allowed"))),
            "workshop_allowed": self._bool(bool(policy.get("workshop_allowed"))),
            "external_upload_allowed": self._bool(bool(policy.get("external_upload_allowed", True))),
            "custom_runtime_allowed": self._bool(bool(policy.get("custom_runtime_allowed"))),
            "startup_json": json.dumps(policy.get("startup") or {}, separators=(",", ":"), sort_keys=True),
        }
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            current = session.execute(
                f"SELECT 1 FROM instance_workspace_policy WHERE instance_id={ph}",
                (instance_id,),
            ).fetchone()
            if current is None:
                session.execute(
                    "INSERT INTO instance_workspace_policy(instance_id,resource_profile_id,storage_limit_bytes,content_mode,mods_allowed,plugins_allowed,workshop_allowed,external_upload_allowed,custom_runtime_allowed,startup_json) "
                    f"VALUES ({self.dialect.parameters(10)})",
                    (instance_id, values["resource_profile_id"], values["storage_limit_bytes"], values["content_mode"], values["mods_allowed"], values["plugins_allowed"], values["workshop_allowed"], values["external_upload_allowed"], values["custom_runtime_allowed"], values["startup_json"]),
                )
            else:
                session.execute(
                    "UPDATE instance_workspace_policy SET "
                    f"resource_profile_id={ph},storage_limit_bytes={ph},content_mode={ph},mods_allowed={ph},plugins_allowed={ph},workshop_allowed={ph},external_upload_allowed={ph},custom_runtime_allowed={ph},startup_json={ph},updated_at={self.dialect.current_timestamp} "
                    f"WHERE instance_id={ph}",
                    (values["resource_profile_id"], values["storage_limit_bytes"], values["content_mode"], values["mods_allowed"], values["plugins_allowed"], values["workshop_allowed"], values["external_upload_allowed"], values["custom_runtime_allowed"], values["startup_json"], instance_id),
                )
        return self.workspace_policy(instance_id)

    # ------------------------------------------------------- granular permissions
    def permission_grants(self, username: str, instance_id: str) -> dict[str, bool]:
        self.initialize(); ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                f"SELECT permission,allowed FROM instance_permission_grants WHERE username={ph} AND instance_id={ph}",
                (str(username).strip().lower(), str(instance_id).strip()),
            ).fetchall()
        return {str(row["permission"]): bool(row["allowed"]) for row in rows}

    def set_permission_grants(self, username: str, instance_id: str, grants: dict[str, Any]) -> dict[str, bool]:
        username = str(username or "").strip().lower(); instance_id = str(instance_id or "").strip()
        if not username or not instance_id:
            raise ValueError("username and instance_id are required")
        invalid = set(grants or {}) - set(INSTANCE_PERMISSIONS)
        if invalid:
            raise ValueError("unknown permissions: " + ", ".join(sorted(invalid)))
        self.instance_context(instance_id); ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            user = session.execute(f"SELECT 1 FROM dashboard_users WHERE username={ph} AND active={ph}", (username, self._bool(True))).fetchone()
            if user is None:
                raise LookupError("active user not found")
            session.execute(f"DELETE FROM instance_permission_grants WHERE username={ph} AND instance_id={ph}", (username, instance_id))
            for permission, allowed in sorted((grants or {}).items()):
                session.execute(
                    "INSERT INTO instance_permission_grants(username,instance_id,permission,allowed) "
                    f"VALUES ({self.dialect.parameters(4)})",
                    (username, instance_id, permission, self._bool(bool(allowed))),
                )
        return self.permission_grants(username, instance_id)

    def effective_permissions_for(self, username: str, instance_id: str) -> set[str]:
        username = str(username or "").strip().lower(); instance_id = str(instance_id or "").strip()
        self.initialize(); ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT permission_profile FROM instance_access WHERE username={ph} AND instance_id={ph}",
                (username, instance_id),
            ).fetchone()
            member = session.execute(
                "SELECT m.account_role FROM customer_account_members m JOIN instances i ON i.customer_id=m.customer_id "
                f"WHERE m.username={ph} AND i.id={ph}",
                (username, instance_id),
            ).fetchone()
        profile = str(row["permission_profile"]) if row is not None else None
        if member is not None and str(member["account_role"]) == "owner":
            profile = "manager"
        if not profile:
            return set()
        return effective_permissions(profile, self.permission_grants(username, instance_id))

    # --------------------------------------------------------------- backup policy
    def backup_policy(self, instance_id: str) -> dict[str, Any]:
        self.instance_context(instance_id); ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT * FROM instance_backup_policy WHERE instance_id={ph}", (instance_id,)).fetchone()
        if row is None:
            return {"instance_id": instance_id, "enabled": True, "schedule_time": "04:00", "healthy_only": True, "keep_single_operational": True}
        result = dict(row)
        for key in ("enabled", "healthy_only", "keep_single_operational"):
            result[key] = bool(result.get(key))
        return result

    def save_backup_policy(self, instance_id: str, *, enabled: bool, schedule_time: str, healthy_only: bool = True) -> dict[str, Any]:
        self.instance_context(instance_id)
        schedule_time = str(schedule_time or "").strip()
        parts = schedule_time.split(":")
        if len(parts) != 2:
            raise ValueError("schedule_time must be HH:MM")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError("schedule_time must be HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("schedule_time must be HH:MM")
        schedule_time = f"{hour:02d}:{minute:02d}"
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            row = session.execute(f"SELECT 1 FROM instance_backup_policy WHERE instance_id={ph}", (instance_id,)).fetchone()
            if row is None:
                session.execute(
                    "INSERT INTO instance_backup_policy(instance_id,enabled,schedule_time,healthy_only,keep_single_operational) "
                    f"VALUES ({self.dialect.parameters(5)})",
                    (instance_id, self._bool(enabled), schedule_time, self._bool(healthy_only), self._bool(True)),
                )
            else:
                session.execute(
                    f"UPDATE instance_backup_policy SET enabled={ph},schedule_time={ph},healthy_only={ph},keep_single_operational={ph},updated_at={self.dialect.current_timestamp} WHERE instance_id={ph}",
                    (self._bool(enabled), schedule_time, self._bool(healthy_only), self._bool(True), instance_id),
                )
        return self.backup_policy(instance_id)

    # ------------------------------------------------------------ upgrade workflow
    def create_contract_change(self, instance_id: str, requested_profile_id: str, requested_by: str, *, change_type: str = "resource_upgrade") -> dict[str, Any]:
        context = self.instance_context(instance_id)
        contract_id = str(context.get("contract_id") or "").strip()
        if not contract_id:
            raise ValueError("instance has no service contract")
        requested_profile_id = str(requested_profile_id or "").strip()
        if not requested_profile_id:
            raise ValueError("requested_profile_id is required")
        policy = self.workspace_policy(instance_id)
        request_id = "contract-change-" + uuid.uuid4().hex
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO contract_change_requests(request_id,customer_id,contract_id,instance_id,current_profile_id,requested_profile_id,change_type,status,requested_by) "
                f"VALUES ({self.dialect.parameters(9)})",
                (request_id, int(context["customer_id"]), contract_id, instance_id, policy.get("resource_profile_id"), requested_profile_id, str(change_type or "resource_upgrade"), "requested", str(requested_by or "").strip() or None),
            )
        return self.contract_change(request_id)

    def contract_change(self, request_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT * FROM contract_change_requests WHERE request_id={ph}", (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        return dict(row)

    def list_contract_changes(self, instance_id: str) -> list[dict[str, Any]]:
        self.instance_context(instance_id); ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                f"SELECT * FROM contract_change_requests WHERE instance_id={ph} ORDER BY requested_at DESC",
                (instance_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_contract_change_status(self, request_id: str, status: str, *, billing_reference: str | None = None, failure_reason: str | None = None) -> dict[str, Any]:
        status = str(status or "").strip().lower()
        if status not in CONTRACT_CHANGE_STATES:
            raise ValueError("invalid contract change status")
        ph = self.dialect.placeholder
        approved = self.dialect.current_timestamp if status in {"approved", "applying", "applied"} else None
        applied = self.dialect.current_timestamp if status == "applied" else None
        assignments = [f"status={ph}", f"billing_reference={ph}", f"failure_reason={ph}", f"updated_at={self.dialect.current_timestamp}"]
        params: list[Any] = [status, str(billing_reference or "").strip() or None, str(failure_reason or "").strip() or None]
        if approved:
            assignments.append(f"approved_at=COALESCE(approved_at,{self.dialect.current_timestamp})")
        if applied:
            assignments.append(f"applied_at=COALESCE(applied_at,{self.dialect.current_timestamp})")
        params.append(request_id)
        with self.session(transaction=True) as session:
            session.execute(f"UPDATE contract_change_requests SET {','.join(assignments)} WHERE request_id={ph}", tuple(params))
        return self.contract_change(request_id)

    # ----------------------------------------------------------------- telemetry
    def record_telemetry(self, instance_id: str, sample: dict[str, Any]) -> None:
        self.instance_context(instance_id)
        values = (
            instance_id,
            sample.get("cpu_percent"), sample.get("memory_bytes"), sample.get("network_rx_bytes"), sample.get("network_tx_bytes"),
            sample.get("players_online"), sample.get("players_max"), sample.get("latency_ms"), str(sample.get("health") or "").strip() or None,
        )
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO instance_telemetry_samples(instance_id,cpu_percent,memory_bytes,network_rx_bytes,network_tx_bytes,players_online,players_max,latency_ms,health) "
                f"VALUES ({self.dialect.parameters(9)})",
                values,
            )

    def telemetry(self, instance_id: str, limit: int = 240) -> list[dict[str, Any]]:
        self.instance_context(instance_id); ph = self.dialect.placeholder; limit = max(1, min(int(limit), 1440))
        with self.session() as session:
            rows = session.execute(
                f"SELECT cpu_percent,memory_bytes,network_rx_bytes,network_tx_bytes,players_online,players_max,latency_ms,health,sampled_at FROM instance_telemetry_samples WHERE instance_id={ph} ORDER BY sampled_at DESC LIMIT {limit}",
                (instance_id,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # -------------------------------------------------------------------- console
    def enqueue_console(self, *, agent_id: str, instance_id: str, command_text: str, requested_by: str) -> dict[str, Any]:
        context = self.instance_context(instance_id)
        if str(context.get("agent_id") or "") != str(agent_id or ""):
            raise PermissionError("instance belongs to another Agent")
        command_text = str(command_text or "").strip()
        if not command_text:
            raise ValueError("console command is required")
        if len(command_text) > 512:
            raise ValueError("console command is too long")
        command_id = "console-cmd-" + uuid.uuid4().hex
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO instance_console_commands(command_id,agent_id,instance_id,command_text,status,requested_by) "
                f"VALUES ({self.dialect.parameters(6)})",
                (command_id, str(agent_id), instance_id, command_text, "queued", str(requested_by)),
            )
        return self.console_command(command_id)

    def console_command(self, command_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(f"SELECT * FROM instance_console_commands WHERE command_id={ph}", (command_id,)).fetchone()
        if row is None:
            raise KeyError(command_id)
        result = dict(row)
        result["result"] = self._decode_json(result.pop("result_json", None), None)
        return result

    def command_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                f"SELECT command_id FROM instance_console_commands WHERE agent_id={ph} AND status IN ('queued','delivered') ORDER BY created_at ASC LIMIT 1",
                (str(agent_id),),
            ).fetchone()
        if row is None:
            return None
        item = self.console_command(str(row["command_id"]))
        return {key: item.get(key) for key in ("command_id", "agent_id", "instance_id", "command_text")}

    def mark_console_delivered(self, command_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE instance_console_commands SET status=CASE WHEN status='queued' THEN 'delivered' ELSE status END,delivered_at=COALESCE(delivered_at,{self.dialect.current_timestamp}),updated_at={self.dialect.current_timestamp} WHERE command_id={ph} AND status IN ('queued','delivered')",
                (command_id,),
            )
        return self.console_command(command_id)

    def apply_console_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        command_id = str(result.get("command_id") or "").strip()
        if not command_id:
            return None
        current = self.console_command(command_id)
        if str(current.get("agent_id")) != str(agent_id):
            raise PermissionError("console command belongs to another Agent")
        if str(result.get("instance_id") or "") != str(current.get("instance_id") or ""):
            raise ValueError("console result instance mismatch")
        status = str(result.get("status") or "").strip().lower()
        if status not in FINAL_CONSOLE_STATES:
            raise ValueError("invalid console result status")
        payload = json.dumps(result, separators=(",", ":"), sort_keys=True)
        error = str(result.get("error") or "").strip()[:512] or None
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE instance_console_commands SET status={ph},result_json={ph},last_error={ph},completed_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE command_id={ph} AND status NOT IN ('completed','failed')",
                (status, payload, error, command_id),
            )
            lines = result.get("output")
            if isinstance(lines, str):
                lines = lines.splitlines()
            if isinstance(lines, list):
                for line in lines[-500:]:
                    text = str(line)[:512]
                    if text:
                        session.execute(
                            "INSERT INTO instance_console_output(instance_id,stream,line) "
                            f"VALUES ({self.dialect.parameters(3)})",
                            (str(current["instance_id"]), "console", text),
                        )
        return self.console_command(command_id)

    def console_output(self, instance_id: str, limit: int = 300) -> list[dict[str, Any]]:
        self.instance_context(instance_id); ph = self.dialect.placeholder; limit = max(1, min(int(limit), 1000))
        with self.session() as session:
            rows = session.execute(
                f"SELECT stream,line,created_at FROM instance_console_output WHERE instance_id={ph} ORDER BY id DESC LIMIT {limit}",
                (instance_id,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]


__all__ = [
    "CONTRACT_CHANGE_STATES",
    "FINAL_CONSOLE_STATES",
    "InstanceWorkspaceRepository",
]
