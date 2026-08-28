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
        actor_role: str | None = None,
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
            ("actor_role", actor_role),
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

    def actor_directory(
        self,
        *,
        query: str = "",
        role: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_all: bool = False,
    ) -> dict[str, Any]:
        """Return identities that can be selected as audit actors.

        System users expose functional name/e-mail. Customer identities also expose
        Customer name, e-mail, document and public code, allowing the audit page to
        locate a person without conflating the access category with the identity.
        Historical audit-only actors are retained as a fallback after account removal.
        """
        self.initialize()
        term = str(query or "").strip().lower()
        normalized_role = str(role or "").strip().lower()
        if normalized_role and normalized_role not in {"admin", "controller", "operator", "customer"}:
            raise ValueError("invalid actor role")
        bounded = max(1, min(int(limit or 100), 200))
        start = max(0, int(offset or 0))
        if not term and not include_all:
            return {"actors": [], "has_more": False, "next_offset": start, "total": 0}

        ph = self.dialect.placeholder
        clauses = ["u.role IN ('admin','controller','operator','customer')"]
        params: list[Any] = []
        if normalized_role:
            clauses.append(f"LOWER(u.role)={ph}")
            params.append(normalized_role)
        if term:
            like = f"%{term}%"
            clauses.append(
                "(LOWER(COALESCE(u.username,'')) LIKE " + ph +
                " OR LOWER(COALESCE(u.full_name,'')) LIKE " + ph +
                " OR LOWER(COALESCE(u.corporate_email,'')) LIKE " + ph +
                " OR LOWER(COALESCE(i.email,'')) LIKE " + ph +
                " OR LOWER(COALESCE(c.name,'')) LIKE " + ph +
                " OR LOWER(COALESCE(c.legal_name,'')) LIKE " + ph +
                " OR LOWER(COALESCE(c.document_number,'')) LIKE " + ph +
                " OR LOWER(COALESCE(c.customer_code,'')) LIKE " + ph + ")"
            )
            params.extend([like] * 8)

        with self.session() as session:
            rows = session.execute(
                "SELECT u.username AS actor_id,u.role AS actor_role,u.active,"
                "COALESCE(u.full_name,c.name,u.username) AS actor_name,"
                "COALESCE(u.corporate_email,i.email,c.account_email,c.email) AS email,"
                "c.document_type,c.document_number,c.customer_code "
                "FROM dashboard_users u "
                "LEFT JOIN customers c ON c.id=u.customer_id "
                "LEFT JOIN customer_user_identities i ON i.username=u.username "
                "WHERE " + " AND ".join(clauses) +
                " ORDER BY LOWER(u.role),LOWER(COALESCE(u.full_name,c.name,u.username)),LOWER(u.username)",
                tuple(params),
            ).fetchall()
            audit_clauses = ["actor_id IS NOT NULL"]
            audit_params: list[Any] = []
            if normalized_role:
                audit_clauses.append(f"LOWER(COALESCE(actor_role,''))={ph}")
                audit_params.append(normalized_role)
            if term:
                like = f"%{term}%"
                audit_clauses.append(
                    "(LOWER(COALESCE(actor_id,'')) LIKE " + ph +
                    " OR LOWER(COALESCE(actor_name,'')) LIKE " + ph + ")"
                )
                audit_params.extend([like, like])
            historical = session.execute(
                "SELECT actor_id,MAX(actor_name) AS actor_name,MAX(actor_role) AS actor_role "
                "FROM activity_audit WHERE " + " AND ".join(audit_clauses) +
                " GROUP BY actor_id ORDER BY actor_id",
                tuple(audit_params),
            ).fetchall()

        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            actor_id = str(item.get("actor_id") or "").strip()
            if not actor_id:
                continue
            item["actor_role"] = str(item.get("actor_role") or "").lower()
            item["active"] = bool(item.get("active", True))
            merged[actor_id] = item
        for row in historical:
            actor_id = str(row["actor_id"] or "").strip()
            if not actor_id or actor_id in merged:
                continue
            merged[actor_id] = {
                "actor_id": actor_id,
                "actor_name": row["actor_name"] or actor_id,
                "actor_role": str(row["actor_role"] or "").lower(),
                "active": False,
                "email": None,
                "document_type": None,
                "document_number": None,
                "customer_code": None,
                "historical": True,
            }

        ordered = sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("actor_role") or ""),
                str(item.get("actor_name") or item.get("actor_id") or "").lower(),
                str(item.get("actor_id") or "").lower(),
            ),
        )
        page = ordered[start:start + bounded]
        next_offset = start + len(page)
        return {
            "actors": page,
            "has_more": next_offset < len(ordered),
            "next_offset": next_offset,
            "total": len(ordered),
        }

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
            roles = session.execute(
                "SELECT DISTINCT role FROM dashboard_users "
                "WHERE role IN ('admin','controller','operator','customer') ORDER BY role"
            ).fetchall()
        actor_roles = [str(row["role"]) for row in roles]
        for standard in ("admin", "controller", "operator", "customer"):
            if standard not in actor_roles:
                actor_roles.append(standard)
        return {
            "actors": [str(row["actor_id"]) for row in actors],
            "actor_roles": actor_roles,
            "actions": [str(row["action"]) for row in actions],
            "categories": [str(row["category"]) for row in categories],
        }


__all__ = ["ActivityAuditRepository", "sanitize_changes"]
