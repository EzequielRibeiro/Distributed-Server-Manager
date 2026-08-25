#!/usr/bin/env python3
"""Persistent, queryable audit trail for every Dashboard activity."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class DashboardActivityRepository:
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

    def record(
        self,
        *,
        username: str | None,
        role: str | None,
        session_id: str | None,
        activity: str,
        category: str,
        result: str,
        method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        remote_address: str | None = None,
        user_agent: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        self.initialize()
        event_id = str(uuid.uuid4())
        payload = json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"))
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO dashboard_activity_log("
                "event_id,username,role,session_id,activity,category,result,method,path,"
                "status_code,remote_address,user_agent,target_type,target_id,details_json"
                f") VALUES ({self.dialect.parameters(15)})",
                (
                    event_id, username, role, session_id, activity, category, result,
                    method, path, status_code, remote_address, user_agent,
                    target_type, target_id, payload,
                ),
            )
        return event_id

    def search(
        self,
        *,
        username: str | None = None,
        category: str | None = None,
        activity: str | None = None,
        result: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.initialize()
        limit = max(1, min(int(limit or 200), 1000))
        ph = self.dialect.placeholder
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("username", username), ("category", category), ("activity", activity), ("result", result)):
            value = str(value or "").strip()
            if value:
                clauses.append(f"{column}={ph}")
                params.append(value)
        if start_at:
            clauses.append(f"created_at>={ph}")
            params.append(start_at)
        if end_at:
            clauses.append(f"created_at<={ph}")
            params.append(end_at)
        sql = (
            "SELECT event_id,username,role,session_id,activity,category,result,method,path,"
            "status_code,remote_address,user_agent,target_type,target_id,details_json,created_at "
            "FROM dashboard_activity_log"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC,event_id DESC LIMIT " + str(limit)
        with self.session() as session:
            rows = session.execute(sql, tuple(params)).fetchall()
        result_rows = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except (TypeError, ValueError):
                item["details"] = {}
            result_rows.append(item)
        return result_rows

    def filter_options(self) -> dict[str, list[str]]:
        self.initialize()
        with self.session() as session:
            users = session.execute(
                "SELECT DISTINCT username FROM dashboard_activity_log WHERE username IS NOT NULL ORDER BY username"
            ).fetchall()
            activities = session.execute(
                "SELECT DISTINCT activity FROM dashboard_activity_log ORDER BY activity"
            ).fetchall()
            categories = session.execute(
                "SELECT DISTINCT category FROM dashboard_activity_log ORDER BY category"
            ).fetchall()
        return {
            "users": [str(row["username"]) for row in users],
            "activities": [str(row["activity"]) for row in activities],
            "categories": [str(row["category"]) for row in categories],
        }


__all__ = ["DashboardActivityRepository"]
