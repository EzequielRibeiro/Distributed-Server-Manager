#!/usr/bin/env python3
"""Administrative customer center persistence and temporary credential state."""
from __future__ import annotations

import secrets
from typing import Any

from admin_management_repository import AdminManagementRepository
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from users import hash_password


class CustomerAdminRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.admin = AdminManagementRepository(backend)

    def initialize(self) -> None:
        self.backend.initialize()
        # Compatibility table for credential onboarding. It is intentionally
        # created idempotently so existing 2.x databases gain the C3 state
        # without depending on a historical migration chain.
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "CREATE TABLE IF NOT EXISTS customer_password_state ("
                    "username VARCHAR(128) PRIMARY KEY,"
                    "must_change_password INTEGER NOT NULL DEFAULT 0,"
                    "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                    "FOREIGN KEY(username) REFERENCES dashboard_users(username) ON DELETE CASCADE"
                    ")"
                )
            finally:
                session.close()

    def _session(self, connection) -> AlertSession:
        return AlertSession(self.backend, connection)

    def search(self, query: str = "") -> list[dict[str, Any]]:
        self.initialize()
        term = str(query or "").strip().lower()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                sql = (
                    "SELECT c.id,c.name,c.email,c.phone,c.status,c.controller_id,"
                    "u.username,u.active,m.account_role "
                    "FROM customers c "
                    "LEFT JOIN dashboard_users u ON u.scope_id=c.id AND u.role='customer' "
                    "LEFT JOIN customer_account_members m ON m.customer_id=c.id AND m.username=u.username "
                )
                params: tuple[Any, ...] = ()
                if term:
                    like = f"%{term}%"
                    sql += (
                        "WHERE LOWER(c.id) LIKE " + ph + " OR LOWER(c.name) LIKE " + ph +
                        " OR LOWER(COALESCE(c.email,'')) LIKE " + ph +
                        " OR LOWER(COALESCE(u.username,'')) LIKE " + ph + " "
                    )
                    params = (like, like, like, like)
                sql += "ORDER BY c.name,c.id,u.username"
                rows = session.execute(sql, params).fetchall()
            finally:
                session.close()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            cid = str(row["id"])
            item = grouped.setdefault(cid, {
                "id": cid, "name": row["name"], "email": row["email"],
                "phone": row["phone"], "status": row["status"],
                "controller_id": row["controller_id"], "users": [],
            })
            if row["username"]:
                item["users"].append({
                    "username": row["username"], "active": bool(row["active"]),
                    "account_role": row["account_role"] or "member",
                })
        return list(grouped.values())

    def detail(self, customer_id: str) -> dict[str, Any]:
        self.initialize()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                customer = session.execute(
                    "SELECT id,name,email,phone,status,controller_id,created_at,updated_at "
                    f"FROM customers WHERE id={ph}", (customer_id,)
                ).fetchone()
                if customer is None:
                    raise ValueError("customer not found")
                users = session.execute(
                    "SELECT u.username,u.active,m.account_role,ui.email,ui.email_verified_at,"
                    "COALESCE(ps.must_change_password,0) AS must_change_password "
                    "FROM dashboard_users u "
                    "LEFT JOIN customer_account_members m ON m.customer_id=u.scope_id AND m.username=u.username "
                    "LEFT JOIN customer_user_identities ui ON ui.username=u.username "
                    "LEFT JOIN customer_password_state ps ON ps.username=u.username "
                    f"WHERE u.role='customer' AND u.scope_id={ph} ORDER BY u.username",
                    (customer_id,),
                ).fetchall()
                contracts = session.execute(
                    "SELECT c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,c.created_at,"
                    "COUNT(ic.instance_id) AS instances_used "
                    "FROM service_contracts c LEFT JOIN instance_contracts ic ON ic.contract_id=c.id "
                    f"WHERE c.customer_id={ph} GROUP BY c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,c.created_at "
                    "ORDER BY c.created_at DESC,c.id",
                    (customer_id,),
                ).fetchall()
                instances = session.execute(
                    "SELECT i.id,i.name,i.game_id,i.status,i.agent_id,ic.contract_id "
                    "FROM instances i LEFT JOIN instance_contracts ic ON ic.instance_id=i.id "
                    f"WHERE i.customer_id={ph} ORDER BY i.name,i.id", (customer_id,)
                ).fetchall()
            finally:
                session.close()
        return {
            "customer": dict(customer),
            "users": [dict(row) | {"active": bool(row["active"]), "must_change_password": bool(row["must_change_password"])} for row in users],
            "contracts": [dict(row) for row in contracts],
            "instances": [dict(row) for row in instances],
        }

    def create_customer(self, *, customer_id: str, name: str, username: str,
                        email: str | None = None, phone: str | None = None,
                        controller_id: str | None = None) -> dict[str, Any]:
        self.initialize()
        temporary_password = self._temporary_password()
        created = self.admin.create_customer(
            customer_id=customer_id, name=name, username=username,
            password_hash=hash_password(temporary_password), controller_id=controller_id,
            email=email, phone=phone,
        )
        username = str(created["username"])
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                # The first login is the Customer account owner. This also
                # repairs the gap in the original CLI create_customer path.
                if session.execute(
                    "SELECT 1 FROM customer_account_members "
                    f"WHERE customer_id={ph} AND username={ph}", (customer_id, username)
                ).fetchone() is None:
                    session.execute(
                        "INSERT INTO customer_account_members(customer_id,username,account_role) "
                        f"VALUES ({self.dialect.parameters(3)})",
                        (customer_id, username, "owner"),
                    )
                if email and session.execute(
                    f"SELECT 1 FROM customer_user_identities WHERE username={ph}", (username,)
                ).fetchone() is None:
                    session.execute(
                        "INSERT INTO customer_user_identities(username,email,email_verified_at) "
                        f"VALUES ({self.dialect.parameters(3)})", (username, email, None)
                    )
                self._set_password_state(session, username, True)
            finally:
                session.close()
        return created | {"temporary_password": temporary_password, "must_change_password": True}

    def reset_password(self, username: str) -> dict[str, Any]:
        self.initialize()
        username = str(username or "").strip().lower()
        ph = self.dialect.placeholder
        temporary_password = self._temporary_password()
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT username,role,scope_id FROM dashboard_users WHERE username={ph}", (username,)
                ).fetchone()
                if row is None or row["role"] != "customer":
                    raise ValueError("customer user not found")
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},updated_at=CURRENT_TIMESTAMP WHERE username={ph}",
                    (hash_password(temporary_password), username),
                )
                self._set_password_state(session, username, True)
            finally:
                session.close()
        return {"username": username, "temporary_password": temporary_password, "must_change_password": True}

    def password_change_required(self, username: str) -> bool:
        self.initialize()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT must_change_password FROM customer_password_state WHERE username={ph}",
                    (username,),
                ).fetchone()
            finally:
                session.close()
        return bool(row and int(row["must_change_password"] or 0))

    def change_temporary_password(self, username: str, new_password: str) -> None:
        self.initialize()
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                row = session.execute(
                    f"SELECT role FROM dashboard_users WHERE username={ph}", (username,)
                ).fetchone()
                if row is None or row["role"] != "customer":
                    raise ValueError("customer user not found")
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},updated_at=CURRENT_TIMESTAMP WHERE username={ph}",
                    (hash_password(new_password), username),
                )
                self._set_password_state(session, username, False)
            finally:
                session.close()

    def create_contract(self, *, customer_id: str, game_id: str, instance_limit: int,
                        contract_id: str | None = None, ends_at: str | None = None) -> dict[str, Any]:
        self.initialize()
        return self.admin.create_contract(
            customer_id=customer_id, game_id=game_id, instance_limit=instance_limit,
            contract_id=contract_id, ends_at=ends_at,
        )

    def _set_password_state(self, session: AlertSession, username: str, required: bool) -> None:
        ph = self.dialect.placeholder
        exists = session.execute(
            f"SELECT 1 FROM customer_password_state WHERE username={ph}", (username,)
        ).fetchone()
        value = 1 if required else 0
        if exists:
            session.execute(
                f"UPDATE customer_password_state SET must_change_password={ph},updated_at=CURRENT_TIMESTAMP WHERE username={ph}",
                (value, username),
            )
        else:
            session.execute(
                "INSERT INTO customer_password_state(username,must_change_password) "
                f"VALUES ({self.dialect.parameters(2)})", (username, value),
            )

    @staticmethod
    def _temporary_password() -> str:
        # 16+ chars, URL-safe and copy-friendly. Plaintext is returned once.
        return secrets.token_urlsafe(12)


__all__ = ["CustomerAdminRepository"]
