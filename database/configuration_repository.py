#!/usr/bin/env python3
"""Backend-neutral persistence and resolution for Universal Configuration."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from configuration_platform import ConfigurationValidationError, deep_merge, normalize_configuration
from event_platform import utc_now
from alert_repository import AlertSession


class ConfigurationRepository:
    def __init__(self, backend):
        self.backend = backend

    def initialize(self) -> None:
        self.backend.initialize()

    @property
    def ph(self) -> str:
        return "?" if self.backend.name == "sqlite" else "%s"

    def _scope_key(self, scope_type: str, scope_id: str | None) -> str:
        return "*" if scope_type == "global" else str(scope_id or "").strip()

    def _row(self, row) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        scope_key = value.pop("scope_key", None)
        value["scope_id"] = None if value.get("scope_type") == "global" else scope_key
        try:
            value["value"] = json.loads(value.pop("value_json"))
        except (json.JSONDecodeError, TypeError):
            value["value"] = {}
        value["kind"] = "CapivaraConfiguration"
        return value

    def _entity_exists(self, table: str, entity_id: str) -> bool:
        if table not in {"agents", "instances"}:
            raise ValueError("unsupported entity table")
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT id FROM {table} WHERE id={self.ph}", (entity_id,)).fetchone()
                return row is not None
            finally:
                session.close()

    def _instance_owned_by(self, agent_id: str, instance_id: str) -> bool:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT id FROM instances WHERE id={self.ph} AND agent_id={self.ph}",
                    (instance_id, agent_id),
                ).fetchone()
                return row is not None
            finally:
                session.close()

    def get(self, *, scope_type: str, scope_id: str | None, namespace: str) -> dict[str, Any] | None:
        key = self._scope_key(scope_type, scope_id)
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM configurations WHERE scope_type={self.ph} AND scope_key={self.ph} AND namespace={self.ph}",
                    (scope_type, key, namespace),
                ).fetchone()
                return self._row(row)
            finally:
                session.close()

    def put(self, raw: Mapping[str, Any], *, updated_by: str | None = None) -> dict[str, Any]:
        config = normalize_configuration(raw)
        if config["scope_type"] == "agent" and not self._entity_exists("agents", str(config["scope_id"])):
            raise ConfigurationValidationError("agent scope_id does not exist")
        if config["scope_type"] == "instance" and not self._entity_exists("instances", str(config["scope_id"])):
            raise ConfigurationValidationError("instance scope_id does not exist")
        existing = self.get(scope_type=config["scope_type"], scope_id=config["scope_id"], namespace=config["namespace"])
        if existing is not None and existing.get("checksum") == config["checksum"]:
            return {"configuration": existing, "changed": False}
        configuration_id = str(existing["configuration_id"]) if existing else str(uuid.uuid4())
        revision = int(existing.get("revision") or 0) + 1 if existing else 1
        key = self._scope_key(config["scope_type"], config["scope_id"])
        now = utc_now()
        value_json = json.dumps(config["value"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if existing:
                    session.execute(
                        f"UPDATE configurations SET schema_version={self.ph},revision={self.ph},value_json={self.ph},checksum={self.ph},updated_by={self.ph},updated_at={self.ph} WHERE configuration_id={self.ph}",
                        (1, revision, value_json, config["checksum"], updated_by, now, configuration_id),
                    )
                else:
                    session.execute(
                        f"INSERT INTO configurations(configuration_id,scope_type,scope_key,namespace,schema_version,revision,value_json,checksum,updated_by,created_at,updated_at) VALUES ({','.join([self.ph]*11)})",
                        (configuration_id, config["scope_type"], key, config["namespace"], 1, revision, value_json, config["checksum"], updated_by, now, now),
                    )
                session.execute(
                    f"INSERT INTO configuration_revisions(configuration_id,revision,value_json,checksum,updated_by,created_at) VALUES ({','.join([self.ph]*6)})",
                    (configuration_id, revision, value_json, config["checksum"], updated_by, now),
                )
            finally:
                session.close()
        stored = self.get(scope_type=config["scope_type"], scope_id=config["scope_id"], namespace=config["namespace"])
        return {"configuration": stored, "changed": True}

    def list_configurations(self, *, scope_type: str | None = None, scope_id: str | None = None, namespace: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("scope_type", scope_type), ("namespace", namespace)):
            if value is not None:
                clauses.append(f"{column}={self.ph}")
                params.append(value)
        if scope_id is not None:
            clauses.append(f"scope_key={self.ph}")
            params.append(scope_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT * FROM configurations{where} ORDER BY namespace,scope_type,scope_key LIMIT {self.ph}", tuple(params)
                ).fetchall()
                return [self._row(row) for row in rows]
            finally:
                session.close()

    def history(self, configuration_id: str) -> list[dict[str, Any]]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT * FROM configuration_revisions WHERE configuration_id={self.ph} ORDER BY revision DESC",
                    (configuration_id,),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["value"] = json.loads(item.pop("value_json"))
                    result.append(item)
                return result
            finally:
                session.close()

    def _merge_rows(self, rows: list[dict[str, Any]], *, target_type: str, target_id: str) -> list[dict[str, Any]]:
        namespaces: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row["namespace"])
            current = namespaces.get(name, {"value": {}, "parts": [], "configuration_refs": []})
            current["value"] = deep_merge(current["value"], row["value"])
            current["parts"].append(f"{row['configuration_id']}:{row['revision']}:{row['checksum']}")
            current["configuration_refs"].append({
                "configuration_id": row["configuration_id"],
                "revision": int(row["revision"]),
                "checksum": row["checksum"],
            })
            namespaces[name] = current
        resolved = []
        for namespace, item in sorted(namespaces.items()):
            digest = hashlib.sha256("|".join(item["parts"]).encode()).hexdigest()
            resolved.append({
                "schema_version": 1,
                "kind": "CapivaraResolvedConfiguration",
                "namespace": namespace,
                "target_type": target_type,
                "target_id": target_id,
                "revision": digest[:16],
                "checksum": digest,
                "value": item["value"],
                "configuration_refs": item["configuration_refs"],
            })
        return resolved

    def resolve_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        if not self._entity_exists("agents", agent_id):
            raise ConfigurationValidationError("agent does not exist")
        rows = self.list_configurations(scope_type="global", limit=1000)
        rows += self.list_configurations(scope_type="agent", scope_id=agent_id, limit=1000)
        return self._merge_rows(rows, target_type="agent", target_id=agent_id)

    def resolve_for_instance(self, agent_id: str, instance_id: str) -> list[dict[str, Any]]:
        if not self._instance_owned_by(agent_id, instance_id):
            raise ConfigurationValidationError("instance does not belong to agent")
        rows = self.list_configurations(scope_type="global", limit=1000)
        rows += self.list_configurations(scope_type="agent", scope_id=agent_id, limit=1000)
        rows += self.list_configurations(scope_type="instance", scope_id=instance_id, limit=1000)
        return self._merge_rows(rows, target_type="instance", target_id=instance_id)

    def instance_ids_for_agent(self, agent_id: str) -> list[str]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT id FROM instances WHERE agent_id={self.ph} ORDER BY id", (agent_id,)
                ).fetchall()
                return [str(row["id"]) for row in rows]
            finally:
                session.close()

    def _applied_state(self, agent_id: str) -> dict[tuple[str, str, str], tuple[str, str]]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT target_type,target_id,namespace,applied_revision,applied_checksum,status FROM agent_configuration_state WHERE agent_id={self.ph}",
                    (agent_id,),
                ).fetchall()
                result = {}
                for row in rows:
                    if str(row.get("status") if hasattr(row, "get") else row["status"]).lower() != "applied":
                        continue
                    item = dict(row)
                    result[(str(item["target_type"]), str(item["target_id"]), str(item["namespace"]))] = (
                        str(item.get("applied_revision") or ""), str(item.get("applied_checksum") or "")
                    )
                return result
            finally:
                session.close()

    def desired_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        commands = self.resolve_for_agent(agent_id)
        for instance_id in self.instance_ids_for_agent(agent_id):
            commands.extend(self.resolve_for_instance(agent_id, instance_id))
        applied = self._applied_state(agent_id)
        pending = []
        for command in commands:
            key = (str(command["target_type"]), str(command["target_id"]), str(command["namespace"]))
            state = applied.get(key)
            if state == (str(command["revision"]), str(command["checksum"])):
                continue
            pending.append(command)
        return pending

    def record_agent_state(self, agent_id: str, reports: list[Mapping[str, Any]]) -> int:
        now = utc_now()
        accepted = 0
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                for report in reports[:1000]:
                    target_type = str(report.get("target_type") or "").strip().lower()
                    target_id = str(report.get("target_id") or "").strip()
                    namespace = str(report.get("namespace") or "").strip().lower()
                    if target_type == "agent":
                        if target_id != agent_id:
                            continue
                    elif target_type == "instance":
                        if not target_id or not self._instance_owned_by(agent_id, target_id):
                            continue
                    else:
                        continue
                    if not namespace:
                        continue
                    desired_revision = str(report.get("desired_revision") or report.get("applied_revision") or "")
                    applied_revision = str(report.get("applied_revision") or "") or None
                    desired_checksum = str(report.get("desired_checksum") or report.get("applied_checksum") or "")
                    applied_checksum = str(report.get("applied_checksum") or "") or None
                    if not desired_revision or not desired_checksum:
                        continue
                    existing = session.execute(
                        f"SELECT agent_id FROM agent_configuration_state WHERE agent_id={self.ph} AND target_type={self.ph} AND target_id={self.ph} AND namespace={self.ph}",
                        (agent_id, target_type, target_id, namespace),
                    ).fetchone()
                    values = (
                        desired_revision, applied_revision, desired_checksum, applied_checksum,
                        str(report.get("status") or "unknown"), report.get("last_error"),
                        report.get("reported_at") or now, now,
                    )
                    if existing:
                        session.execute(
                            f"UPDATE agent_configuration_state SET desired_revision={self.ph},applied_revision={self.ph},desired_checksum={self.ph},applied_checksum={self.ph},status={self.ph},last_error={self.ph},reported_at={self.ph},updated_at={self.ph} WHERE agent_id={self.ph} AND target_type={self.ph} AND target_id={self.ph} AND namespace={self.ph}",
                            (*values, agent_id, target_type, target_id, namespace),
                        )
                    else:
                        session.execute(
                            f"INSERT INTO agent_configuration_state(agent_id,target_type,target_id,namespace,desired_revision,applied_revision,desired_checksum,applied_checksum,status,last_error,reported_at,updated_at) VALUES ({','.join([self.ph]*12)})",
                            (agent_id, target_type, target_id, namespace, *values),
                        )
                    accepted += 1
            finally:
                session.close()
        return accepted


__all__ = ["ConfigurationRepository"]
