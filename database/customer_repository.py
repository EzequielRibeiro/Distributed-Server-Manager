#!/usr/bin/env python3
"""Backend-independent customer administration queries."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


DOCUMENT_RE = re.compile(r"\D+")
VALID_STATUSES = {"active", "suspended", "cancelled"}


def normalize_document(value: Any) -> str:
    return DOCUMENT_RE.sub("", str(value or ""))


def mask_document(document_type: str | None, document_number: Any) -> str | None:
    digits = normalize_document(document_number)
    if not digits:
        return None
    if document_type == "cpf" and len(digits) == 11:
        return f"***.***.***-{digits[-2:]}"
    if document_type == "cnpj" and len(digits) == 14:
        return f"**.***.***/****-{digits[-2:]}"
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def customer_to_public(row: Any) -> dict[str, Any]:
    data = dict(row)
    raw = data.pop("document_number", None)
    data["document"] = mask_document(data.get("document_type"), raw)
    return data


class CustomerRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(self) -> Iterator[AlertSession]:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def search_customers(
        self, *, query: str = "", status: str = "",
        limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        self.initialize()
        query = str(query or "").strip()
        status = str(status or "").strip()
        try:
            limit, offset = int(limit), int(offset)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid pagination") from exc
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        ph = self.dialect.placeholder
        conditions: list[str] = []
        parameters: list[Any] = []
        if query:
            like = f"%{query.lower()}%"
            columns = (
                "c.id", "c.name", "c.legal_name", "c.email",
                "c.phone", "c.billing_customer_id",
            )
            search = [f"LOWER(COALESCE({column}, '')) LIKE {ph}" for column in columns]
            values = [like] * len(columns)
            document = normalize_document(query)
            if len(document) >= 4:
                search.append(f"COALESCE(c.document_number, '') LIKE {ph}")
                values.append(f"%{document}%")
            conditions.append("(" + " OR ".join(search) + ")")
            parameters.extend(values)
        if status:
            if status not in VALID_STATUSES:
                raise ValueError("invalid customer status")
            conditions.append(f"c.status={ph}")
            parameters.append(status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        active = "du.active" if self.backend.name == "postgresql" else "du.active = 1"
        count_sql = "SELECT COUNT(*) AS total FROM customers c" + where
        search_sql = f"""
            SELECT c.id,c.controller_id,c.name,c.legal_name,c.email,c.phone,
                   c.document_type,c.document_number,c.status,c.billing_provider,
                   c.billing_customer_id,c.billing_status,c.billing_synced_at,
                   c.created_at,c.updated_at,
                   COUNT(DISTINCT i.id) AS instance_count,
                   COUNT(DISTINCT sc.id) AS contract_count,
                   COUNT(DISTINCT CASE WHEN {active} THEN du.username END) AS user_count
            FROM customers c
            LEFT JOIN instances i ON i.customer_id=c.id
            LEFT JOIN service_contracts sc ON sc.customer_id=c.id
            LEFT JOIN dashboard_users du ON du.role='customer' AND du.scope_id=c.id
            {where}
            GROUP BY c.id
            ORDER BY LOWER(c.name),c.id
            LIMIT {ph} OFFSET {ph}
        """
        with self.session() as session:
            total = int(session.execute(count_sql, parameters).fetchone()["total"])
            rows = session.execute(search_sql, (*parameters, limit, offset)).fetchall()
        items = [customer_to_public(row) for row in rows]
        return {"items": items, "total": total, "count": len(items),
                "limit": limit, "offset": offset,
                "has_more": offset + len(items) < total}

    def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        self.initialize()
        customer_id = str(customer_id or "").strip()
        if not customer_id:
            return None
        ph = self.dialect.placeholder
        queries = {
            "customer": f"""SELECT c.id,c.controller_id,c.name,c.legal_name,c.email,c.phone,
                c.document_type,c.document_number,c.status,c.billing_provider,
                c.billing_customer_id,c.billing_status,c.billing_synced_at,
                c.created_at,c.updated_at,ctrl.name AS controller_name,
                ctrl.status AS controller_status FROM customers c
                LEFT JOIN controllers ctrl ON ctrl.id=c.controller_id WHERE c.id={ph}""",
            "users": f"SELECT username,role,active,created_at,updated_at FROM dashboard_users WHERE role='customer' AND scope_id={ph} ORDER BY username",
            "contracts": f"""SELECT sc.id,sc.game_id,sc.status,sc.instance_limit,sc.starts_at,
                sc.ends_at,sc.created_at,COUNT(ic.instance_id) AS instances_used
                FROM service_contracts sc LEFT JOIN instance_contracts ic ON ic.contract_id=sc.id
                WHERE sc.customer_id={ph} GROUP BY sc.id ORDER BY sc.created_at DESC,sc.id""",
            "instances": f"""SELECT i.id,i.node_id,i.game_id,i.name,i.status,i.controller_id,
                i.agent_id,i.customer_id,i.created_at,a.name AS agent_name,a.status AS agent_status,
                ic.contract_id FROM instances i LEFT JOIN agents a ON a.id=i.agent_id
                LEFT JOIN instance_contracts ic ON ic.instance_id=i.id WHERE i.customer_id={ph}
                ORDER BY LOWER(i.name),i.id""",
            "permissions": f"""SELECT ia.username,ia.instance_id,ia.permission_profile
                FROM instance_access ia INNER JOIN dashboard_users du ON du.username=ia.username
                WHERE du.role='customer' AND du.scope_id={ph} ORDER BY ia.username,ia.instance_id""",
            "audit": f"""SELECT al.username,al.instance_id,al.action,al.result,al.details
                FROM audit_log al WHERE al.username IN (SELECT username FROM dashboard_users
                WHERE role='customer' AND scope_id={ph}) OR al.instance_id IN
                (SELECT id FROM instances WHERE customer_id={ph})
                ORDER BY al.created_at DESC,al.id DESC LIMIT 100""",
        }
        with self.session() as session:
            customer = session.execute(queries["customer"], (customer_id,)).fetchone()
            if customer is None:
                return None
            result = customer_to_public(customer)
            for name in ("users", "contracts", "instances", "permissions"):
                result[name] = [dict(row) for row in session.execute(
                    queries[name], (customer_id,)
                ).fetchall()]
            result["audit"] = [dict(row) for row in session.execute(
                queries["audit"], (customer_id, customer_id)
            ).fetchall()]
        return result

    def close(self) -> None:
        self.backend.close()
