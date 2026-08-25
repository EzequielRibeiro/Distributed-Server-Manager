#!/usr/bin/env python3
"""Canonical Customer user lifecycle persistence facade for Baseline v2."""
from __future__ import annotations

import json
from typing import Any

from customer_reference import resolve_customer_reference
from customer_team_repository import (
    ACCOUNT_ROLES,
    DELEGABLE_ACCOUNT_ROLES,
    INSTANCE_PROFILES,
    CustomerTeamRepository,
)


class CustomerUserRepository(CustomerTeamRepository):
    @staticmethod
    def _customer_pk(customer_reference: Any) -> int:
        return resolve_customer_reference(
            customer_reference,
            public_only=isinstance(customer_reference, str),
        )

    def require_membership(self, customer_reference: Any, username: str) -> str:
        role = self.account_role(customer_reference, username)
        if role is None:
            raise PermissionError("customer account membership is required")
        return role

    def require_instance(self, customer_reference: Any, instance_id: str) -> dict:
        instance_id = str(instance_id).strip()
        for instance in self.list_instances(customer_reference):
            if str(instance.get("id")) == instance_id:
                return instance
        raise PermissionError("instance is outside customer scope")

    def owner_count(self, customer_reference: Any) -> int:
        return sum(
            1
            for member in self.list_members(customer_reference)
            if member.get("account_role") == "owner"
        )

    def transfer_owner(self, customer_reference: Any, current_owner: str, new_owner: str) -> None:
        customer_id = self._customer_pk(customer_reference)
        current_owner = str(current_owner).strip().lower()
        new_owner = str(new_owner).strip().lower()
        if not current_owner or not new_owner or current_owner == new_owner:
            raise ValueError("a different target owner is required")
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                current = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, current_owner),
                ).fetchone()
                target = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, new_owner),
                ).fetchone()
                if current is None or str(current["account_role"]) != "owner":
                    raise PermissionError("current user is not the customer owner")
                if target is None:
                    raise LookupError("target owner must already be a customer member")
                active = session.execute(
                    f"SELECT active FROM dashboard_users WHERE username={ph} AND role='customer' AND customer_id={ph}",
                    (new_owner, customer_id),
                ).fetchone()
                if active is None or not bool(active["active"]):
                    raise ValueError("target owner must be active")
                session.execute(
                    f"UPDATE customer_account_members SET account_role='manager',updated_at={self.dialect.current_timestamp} WHERE customer_id={ph} AND username={ph}",
                    (customer_id, current_owner),
                )
                session.execute(
                    f"UPDATE customer_account_members SET account_role='owner',updated_at={self.dialect.current_timestamp} WHERE customer_id={ph} AND username={ph}",
                    (customer_id, new_owner),
                )
            finally:
                session.close()

    def set_active(self, customer_reference: Any, username: str, active: bool) -> None:
        customer_id = self._customer_pk(customer_reference)
        username = str(username).strip().lower()
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                member = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if member is None:
                    raise LookupError("customer member not found")
                if str(member["account_role"]) == "owner" and not active:
                    raise PermissionError("customer owner cannot be disabled")
                session.execute(
                    f"UPDATE dashboard_users SET active={ph} WHERE username={ph} AND role='customer' AND customer_id={ph}",
                    (bool(active), username, customer_id),
                )
            finally:
                session.close()

    def reset_password(self, customer_reference: Any, username: str, password_hash: str) -> None:
        customer_id = self._customer_pk(customer_reference)
        username = str(username).strip().lower()
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                member = session.execute(
                    f"SELECT 1 FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if member is None:
                    raise LookupError("customer member not found")
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph} WHERE username={ph} AND role='customer' AND customer_id={ph}",
                    (password_hash, username, customer_id),
                )
            finally:
                session.close()

    def list_activity(self, customer_reference: Any, limit: int = 100) -> list[dict[str, Any]]:
        customer_id = self._customer_pk(customer_reference)
        limit = max(1, min(int(limit), 250))
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT username,instance_id,action,result,details,created_at FROM audit_log "
                    f"WHERE username IN (SELECT username FROM customer_account_members WHERE customer_id={ph}) "
                    f"OR instance_id IN (SELECT id FROM instances WHERE customer_id={ph}) "
                    f"ORDER BY created_at DESC LIMIT {limit}",
                    (customer_id, customer_id),
                ).fetchall()
            finally:
                session.close()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.get("details")
            if isinstance(raw, str):
                try:
                    item["details"] = json.loads(raw)
                except (TypeError, ValueError):
                    pass
            result.append(item)
        return result


__all__ = [
    "ACCOUNT_ROLES",
    "DELEGABLE_ACCOUNT_ROLES",
    "INSTANCE_PROFILES",
    "CustomerUserRepository",
]
