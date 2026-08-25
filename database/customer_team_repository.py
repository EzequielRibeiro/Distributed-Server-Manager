#!/usr/bin/env python3
"""Customer team and per-instance access persistence for Baseline v2."""
from __future__ import annotations

from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_reference import resolve_customer_reference

ACCOUNT_ROLES = {"owner", "manager", "member"}
DELEGABLE_ACCOUNT_ROLES = {"manager", "member"}
INSTANCE_PROFILES = {"viewer", "operator", "manager"}


class CustomerTeamRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _session(self, connection: Any) -> AlertSession:
        return AlertSession(self.backend, connection)

    @staticmethod
    def _pk(customer_reference: Any) -> int:
        return resolve_customer_reference(
            customer_reference,
            public_only=isinstance(customer_reference, str),
        )

    def account_role(self, customer_reference: Any, username: str) -> str | None:
        customer_id = self._pk(customer_reference)
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                return None if row is None else str(row["account_role"])
            finally:
                session.close()

    def list_instances(self, customer_reference: Any) -> list[dict[str, Any]]:
        customer_id = self._pk(customer_reference)
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT id,name,game_id,status FROM instances "
                    f"WHERE customer_id={ph} ORDER BY LOWER(name),id",
                    (customer_id,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                session.close()

    def list_members(self, customer_reference: Any) -> list[dict[str, Any]]:
        customer_id = self._pk(customer_reference)
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT m.username,m.account_role,u.active,m.created_at,m.updated_at "
                    "FROM customer_account_members m JOIN dashboard_users u ON u.username=m.username "
                    f"WHERE m.customer_id={ph} "
                    "ORDER BY CASE m.account_role WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END,m.username",
                    (customer_id,),
                ).fetchall()
                access_rows = session.execute(
                    "SELECT ia.username,ia.instance_id,ia.permission_profile FROM instance_access ia "
                    "JOIN dashboard_users u ON u.username=ia.username "
                    f"WHERE u.role='customer' AND u.customer_id={ph} ORDER BY ia.username,ia.instance_id",
                    (customer_id,),
                ).fetchall()
            finally:
                session.close()
        access: dict[str, dict[str, str]] = {}
        for row in access_rows:
            access.setdefault(str(row["username"]), {})[str(row["instance_id"])] = str(row["permission_profile"])
        result = []
        for row in rows:
            item = dict(row)
            item["instance_access"] = access.get(str(row["username"]), {})
            result.append(item)
        return result

    def create_member(
        self,
        customer_reference: Any,
        username: str,
        password_hash: str,
        account_role: str = "member",
    ) -> None:
        customer_id = self._pk(customer_reference)
        if account_role not in DELEGABLE_ACCOUNT_ROLES:
            raise ValueError("invalid delegated account role")
        self.backend.initialize(); ph = self.dialect.placeholder
        username = username.strip().lower()
        active_value = True if self.backend.name == "postgresql" else 1
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                existing = session.execute(
                    f"SELECT role,customer_id FROM dashboard_users WHERE username={ph}",
                    (username,),
                ).fetchone()
                if existing is None:
                    session.execute(
                        "INSERT INTO dashboard_users(username,password_hash,role,customer_id,active) "
                        f"VALUES ({self.dialect.parameters(5)})",
                        (username, password_hash, "customer", customer_id, active_value),
                    )
                elif existing["role"] != "customer" or int(existing["customer_id"] or 0) != customer_id:
                    raise ValueError("username is already linked to another account")
                member = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if member is not None:
                    raise ValueError("user is already a member of this customer")
                session.execute(
                    "INSERT INTO customer_account_members(customer_id,username,account_role) "
                    f"VALUES ({self.dialect.parameters(3)})",
                    (customer_id, username, account_role),
                )
            finally:
                session.close()

    def set_account_role(self, customer_reference: Any, username: str, account_role: str) -> None:
        customer_id = self._pk(customer_reference)
        if account_role not in DELEGABLE_ACCOUNT_ROLES:
            raise ValueError("invalid delegated account role")
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if row is None:
                    raise LookupError("customer member not found")
                if row["account_role"] == "owner":
                    raise PermissionError("owner account role cannot be delegated or replaced here")
                session.execute(
                    f"UPDATE customer_account_members SET account_role={ph},updated_at={self.dialect.current_timestamp} "
                    f"WHERE customer_id={ph} AND username={ph}",
                    (account_role, customer_id, username),
                )
            finally:
                session.close()

    def set_instance_access(
        self,
        customer_reference: Any,
        username: str,
        instance_id: str,
        permission_profile: str | None,
    ) -> None:
        customer_id = self._pk(customer_reference)
        if permission_profile not in INSTANCE_PROFILES | {None}:
            raise ValueError("invalid instance permission profile")
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                member = session.execute(
                    "SELECT 1 FROM customer_account_members "
                    f"WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if member is None:
                    raise LookupError("customer member not found")
                instance = session.execute(
                    f"SELECT 1 FROM instances WHERE id={ph} AND customer_id={ph}",
                    (instance_id, customer_id),
                ).fetchone()
                if instance is None:
                    raise PermissionError("instance is outside customer scope")
                if permission_profile is None:
                    session.execute(
                        f"DELETE FROM instance_access WHERE username={ph} AND instance_id={ph}",
                        (username, instance_id),
                    )
                    return
                current = session.execute(
                    f"SELECT 1 FROM instance_access WHERE username={ph} AND instance_id={ph}",
                    (username, instance_id),
                ).fetchone()
                if current is None:
                    session.execute(
                        "INSERT INTO instance_access(username,instance_id,permission_profile) "
                        f"VALUES ({self.dialect.parameters(3)})",
                        (username, instance_id, permission_profile),
                    )
                else:
                    session.execute(
                        f"UPDATE instance_access SET permission_profile={ph} WHERE username={ph} AND instance_id={ph}",
                        (permission_profile, username, instance_id),
                    )
            finally:
                session.close()

    def permission_profile(
        self,
        customer_reference: Any,
        username: str,
        instance_id: str,
    ) -> str | None:
        customer_id = self._pk(customer_reference)
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    "SELECT ia.permission_profile FROM instance_access ia "
                    "JOIN dashboard_users u ON u.username=ia.username "
                    f"JOIN instances i ON i.id=ia.instance_id WHERE ia.username={ph} AND ia.instance_id={ph} "
                    f"AND u.role='customer' AND u.customer_id={ph} AND i.customer_id={ph}",
                    (username, instance_id, customer_id, customer_id),
                ).fetchone()
                return None if row is None else str(row["permission_profile"])
            finally:
                session.close()

    def remove_member(self, customer_reference: Any, username: str) -> None:
        customer_id = self._pk(customer_reference)
        self.backend.initialize(); ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT account_role FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if row is None:
                    raise LookupError("customer member not found")
                if row["account_role"] == "owner":
                    raise PermissionError("owner cannot be removed from the customer account")
                session.execute(
                    f"DELETE FROM instance_access WHERE username={ph} AND instance_id IN "
                    f"(SELECT id FROM instances WHERE customer_id={ph})",
                    (username, customer_id),
                )
                session.execute(
                    f"DELETE FROM customer_account_members WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                )
                session.execute(
                    f"DELETE FROM dashboard_users WHERE username={ph} AND role='customer' AND customer_id={ph}",
                    (username, customer_id),
                )
            finally:
                session.close()
