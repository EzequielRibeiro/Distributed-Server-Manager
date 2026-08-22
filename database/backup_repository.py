#!/usr/bin/env python3
"""Backend-neutral persistence and scheduling for Universal Smart Backup."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from alert_repository import AlertSession
from backup_intelligence import aggregate_health, evaluate_policy
from backup_platform import BackupValidationError, normalize_policy
from event_platform import utc_now


def _epoch(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


class BackupRepository:
    def __init__(self, backend):
        self.backend = backend

    def initialize(self):
        self.backend.initialize()

    @property
    def ph(self):
        return "?" if self.backend.name == "sqlite" else "%s"

    def _instance(self, iid):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return session.execute(
                    f"SELECT id,agent_id FROM instances WHERE id={self.ph}",
                    (iid,),
                ).fetchone()
            finally:
                session.close()

    def _policy(self, row):
        if row is None:
            return None
        value = dict(row)
        value["enabled"] = bool(value.get("enabled"))
        for column, name in (("include_json", "include_paths"), ("exclude_json", "exclude_paths")):
            try:
                value[name] = json.loads(value.pop(column) or "[]")
            except Exception:
                value[name] = []
        value["schema_version"] = 1
        value["kind"] = "CapivaraBackupPolicy"
        return value

    def get_policy(self, instance_id):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return self._policy(
                    session.execute(
                        f"SELECT * FROM backup_policies WHERE instance_id={self.ph}",
                        (instance_id,),
                    ).fetchone()
                )
            finally:
                session.close()

    def put_policy(self, raw: Mapping[str, Any], *, requested_by=None):
        iid = str((raw or {}).get("instance_id") or "").strip()
        instance = self._instance(iid)
        if instance is None:
            raise BackupValidationError("instance does not exist")
        aid = str(dict(instance).get("agent_id") or "")
        body = dict(raw or {})
        body["agent_id"] = aid
        item = normalize_policy(body, expected_agent_id=aid)
        old = self.get_policy(iid)
        if old and old.get("checksum") == item["checksum"]:
            return {"policy": old, "changed": False}
        pid = str(old["policy_id"]) if old else str(uuid.uuid4())
        revision = int(old.get("revision") or 0) + 1 if old else 1
        now = utc_now()
        includes = json.dumps(item["include_paths"], separators=(",", ":"))
        excludes = json.dumps(item["exclude_paths"], separators=(",", ":"))
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                values = (
                    item["agent_id"],
                    1 if item["enabled"] else 0,
                    item["mode"],
                    item["consistency"],
                    item["compression"],
                    item["interval_seconds"],
                    item["retention_count"],
                    includes,
                    excludes,
                    revision,
                    item["checksum"],
                    requested_by,
                    now,
                )
                if old:
                    session.execute(
                        f"UPDATE backup_policies SET agent_id={self.ph},enabled={self.ph},mode={self.ph},consistency={self.ph},compression={self.ph},interval_seconds={self.ph},retention_count={self.ph},include_json={self.ph},exclude_json={self.ph},revision={self.ph},checksum={self.ph},requested_by={self.ph},updated_at={self.ph} WHERE policy_id={self.ph}",
                        (*values, pid),
                    )
                else:
                    session.execute(
                        f"INSERT INTO backup_policies(policy_id,instance_id,agent_id,enabled,mode,consistency,compression,interval_seconds,retention_count,include_json,exclude_json,revision,checksum,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*16)})",
                        (pid, iid, *values, now),
                    )
                session.execute(
                    f"INSERT INTO backup_policy_revisions(policy_id,revision,enabled,mode,consistency,compression,interval_seconds,retention_count,include_json,exclude_json,checksum,requested_by,created_at) VALUES ({','.join([self.ph]*13)})",
                    (
                        pid,
                        revision,
                        1 if item["enabled"] else 0,
                        item["mode"],
                        item["consistency"],
                        item["compression"],
                        item["interval_seconds"],
                        item["retention_count"],
                        includes,
                        excludes,
                        item["checksum"],
                        requested_by,
                        now,
                    ),
                )
            finally:
                session.close()
        return {"policy": self.get_policy(iid), "changed": True}

    def list_policies(self, *, agent_id=None, limit=500):
        where = ""
        params = []
        if agent_id:
            where = f" WHERE agent_id={self.ph}"
            params.append(agent_id)
        params.append(max(1, min(int(limit), 2000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return [
                    self._policy(row)
                    for row in session.execute(
                        f"SELECT * FROM backup_policies{where} ORDER BY instance_id LIMIT {self.ph}",
                        tuple(params),
                    ).fetchall()
                ]
            finally:
                session.close()

    def history(self, policy_id):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return [
                    dict(row)
                    for row in session.execute(
                        f"SELECT * FROM backup_policy_revisions WHERE policy_id={self.ph} ORDER BY revision DESC",
                        (policy_id,),
                    ).fetchall()
                ]
            finally:
                session.close()

    def request(self, instance_id, *, action="create", backup_id=None, reason="manual", requested_by=None):
        instance = self._instance(instance_id)
        if instance is None:
            raise BackupValidationError("instance does not exist")
        aid = str(dict(instance).get("agent_id") or "")
        policy = self.get_policy(instance_id)
        command_id = str(uuid.uuid4())
        now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    f"INSERT INTO backup_jobs(command_id,backup_id,instance_id,agent_id,action,policy_revision,status,reason,requested_by,created_at,updated_at) VALUES ({','.join([self.ph]*11)})",
                    (
                        command_id,
                        backup_id,
                        instance_id,
                        aid,
                        action,
                        int(policy.get("revision")) if policy else None,
                        "pending",
                        reason,
                        requested_by,
                        now,
                        now,
                    ),
                )
            finally:
                session.close()
        return self.get_job(command_id)

    def get_job(self, command_id):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM backup_jobs WHERE command_id={self.ph}",
                    (command_id,),
                ).fetchone()
                return dict(row) if row else None
            finally:
                session.close()

    def list_jobs(self, *, instance_id=None, agent_id=None, status=None, limit=500):
        clauses = []
        params = []
        for column, value in (("instance_id", instance_id), ("agent_id", agent_id), ("status", status)):
            if value:
                clauses.append(f"{column}={self.ph}")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 2000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return [
                    dict(row)
                    for row in session.execute(
                        f"SELECT * FROM backup_jobs{where} ORDER BY created_at DESC LIMIT {self.ph}",
                        tuple(params),
                    ).fetchall()
                ]
            finally:
                session.close()

    def health(self, *, instance_id=None, agent_id=None, now=None):
        if instance_id:
            policy = self.get_policy(instance_id)
            if policy is None:
                raise BackupValidationError("backup policy does not exist")
            if agent_id and str(policy.get("agent_id") or "") != str(agent_id):
                return aggregate_health([])
            return evaluate_policy(policy, self.list_jobs(instance_id=instance_id, limit=100), now=now)
        rows = []
        for policy in self.list_policies(agent_id=agent_id):
            rows.append(
                evaluate_policy(
                    policy,
                    self.list_jobs(instance_id=policy["instance_id"], limit=100),
                    now=now,
                )
            )
        return aggregate_health(rows)

    def schedule_due(self, agent_id, *, now_epoch=None):
        now_epoch = float(
            now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        )
        created = []
        for policy in self.list_policies(agent_id=agent_id):
            if not policy["enabled"]:
                continue
            jobs = self.list_jobs(instance_id=policy["instance_id"], limit=50)
            if any(job["status"] in {"pending", "running"} for job in jobs):
                continue
            last = max(
                (
                    _epoch(job.get("completed_at"))
                    for job in jobs
                    if job.get("action") == "create" and job.get("status") == "completed"
                ),
                default=0,
            )
            if last and now_epoch - last < int(policy["interval_seconds"]):
                continue
            created.append(
                self.request(
                    policy["instance_id"],
                    action="create",
                    reason="schedule",
                    requested_by="scheduler",
                )
            )
        return created

    def commands_for_agent(self, agent_id):
        self.schedule_due(agent_id)
        output = []
        for job in reversed(self.list_jobs(agent_id=agent_id, status="pending", limit=100)):
            policy = self.get_policy(job["instance_id"])
            output.append(
                {
                    "schema_version": 1,
                    "kind": "CapivaraBackupCommand",
                    "command_id": job["command_id"],
                    "action": job["action"],
                    "instance_id": job["instance_id"],
                    "agent_id": agent_id,
                    "backup_id": job.get("backup_id"),
                    "reason": job.get("reason"),
                    "policy": policy or {},
                    "requested_by": job.get("requested_by"),
                }
            )
        return output

    def record_agent_state(self, agent_id, reports: list[Mapping[str, Any]]):
        accepted = 0
        now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                for report in reports[:500]:
                    command_id = str(report.get("command_id") or "")
                    row = session.execute(
                        f"SELECT * FROM backup_jobs WHERE command_id={self.ph} AND agent_id={self.ph}",
                        (command_id, agent_id),
                    ).fetchone()
                    if not row:
                        continue
                    status = str(report.get("status") or "failed").lower()
                    if status not in {"running", "completed", "failed"}:
                        continue
                    backup_id = report.get("backup_id") or dict(row).get("backup_id")
                    session.execute(
                        f"UPDATE backup_jobs SET backup_id={self.ph},status={self.ph},size_bytes={self.ph},sha256={self.ph},artifact_path={self.ph},started_at={self.ph},completed_at={self.ph},last_error={self.ph},updated_at={self.ph} WHERE command_id={self.ph}",
                        (
                            backup_id,
                            status,
                            report.get("size_bytes"),
                            report.get("sha256"),
                            report.get("artifact_path"),
                            report.get("started_at") or (now if status == "running" else None),
                            report.get("completed_at") or (now if status in {"completed", "failed"} else None),
                            report.get("last_error"),
                            now,
                            command_id,
                        ),
                    )
                    accepted += 1
            finally:
                session.close()
        return accepted


__all__ = ["BackupRepository"]
