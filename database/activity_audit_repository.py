#!/usr/bin/env python3
"""Backend-neutral semantic operator audit persistence."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend

_SENSITIVE_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "credential",
    "private_key",
    "api_key",
    "authorization",
)


def _sensitive(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def sanitize_changes(changes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove secret values while retaining the fact that a field changed."""
    clean: dict[str, Any] = {}
    for key, value in dict(changes or {}).items():
        if _sensitive(str(key)):
            clean[str(key)] = {"changed": True}
            continue
        if isinstance(value, Mapping):
            item = dict(value)
            before = item.get("before")
            after = item.get("after")
            if before == after:
                continue
            clean[str(key)] = {"before": before, "after": after}
        else:
            clean[str(key)] = value
    return clean


class ActivityAuditRepository:
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

    def record_action(
        self,
        *,
        actor_id: str | None,
        actor_name: str | None,
        actor_role: str | None,
        action: str,
        category: str,
        result: str,
        summary: str,
        target_type: str | None = None,
        target_id: str | None = None,
        target_name: str | None = None,
        changes: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        remote_address: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        self.initialize()
        action = str(action or "").strip()
        category = str(category or "").strip()
        result = str(result or "").strip().lower()
        summary = str(summary or "").strip()
        if not action or not category or not result or not summary:
            raise ValueError("action, category, result and summary are required")
        activity_id = str(uuid.uuid4())
        payload = json.dumps(
            sanitize_changes(changes),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO activity_audit("
                "activity_id,actor_id,actor_name,actor_role,action,category,"
                "target_type,target_id,target_name,result,summary,changes_json,"
                "correlation_id,remote_address,user_agent"
                f") VALUES ({self.dialect.parameters(15)})",
                (
                    activity_id,
                    actor_id,
                    actor_name,
                    actor_role,
                    action,
                    category,
                    target_type,
                    target_id,
                    target_name,
                    result,
                    summary,
                    payload,
                    correlation_id,
                    remote_address,
                    user_agent,
                ),
            )
        return activity_id

    def search(
        self,
        *,
        actor_id: str | None = None,
        category: str | None = None,
        action: str | None = None,
        result: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.initialize()
        ph = self.dialect.placeholder
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("actor_id", actor_id),
            ("category", category),
            ("action", action),
            ("result", result),
            ("target_type", target_type),
            ("target_id", target_id),
        ):
            value = str(value or "").strip()
            if value:
                clauses.append(f"{column}={ph}")
                params.append(value)
        if start_at:
            clauses.append(f"occurred_at>={ph}")
            params.append(start_at)
        if end_at:
            clauses.append(f"occurred_at<={ph}")
            params.append(end_at)
        bounded = max(1, min(int(limit or 200), 1000))
        sql = "SELECT * FROM activity_audit"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY occurred_at DESC,activity_id DESC LIMIT {ph}"
        params.append(bounded)
        with self.session() as session:
            rows = session.execute(sql, tuple(params)).fetchall()
        result_rows: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["changes"] = json.loads(str(item.pop("changes_json") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                item["changes"] = {}
            result_rows.append(item)
        return result_rows

    def filter_options(self) -> dict[str, list[str]]:
        self.initialize()
        with self.session() as session:
            actors = session.execute(
                "SELECT DISTINCT actor_id FROM activity_audit WHERE actor_id IS NOT NULL ORDER BY actor_id"
            ).fetchall()
            actions = session.execute(
                "SELECT DISTINCT action FROM activity_audit ORDER BY action"
            ).fetchall()
            categories = session.execute(
                "SELECT DISTINCT category FROM activity_audit ORDER BY category"
            ).fetchall()
        return {
            "actors": [str(row["actor_id"]) for row in actors],
            "actions": [str(row["action"]) for row in actions],
            "categories": [str(row["category"]) for row in categories],
        }


__all__ = ["ActivityAuditRepository", "sanitize_changes"]
