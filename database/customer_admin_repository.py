#!/usr/bin/env python3
"""Administrative Customer persistence for Database Baseline v2."""
from __future__ import annotations

import json
import secrets
from typing import Any

from admin_management_repository import AdminManagementRepository
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_reference import resolve_customer_reference
from users import hash_password

ACCOUNT_ROLES = {"owner", "manager", "member"}
INSTANCE_PROFILES = {"viewer", "operator", "manager"}


class CustomerAdminRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.admin = AdminManagementRepository(backend)

    def initialize(self) -> None:
        # Baseline v2 is authoritative. Repositories never create compatibility
        # tables or backfill historical Customer layouts at runtime.
        self.backend.initialize()

    def _session(self, connection) -> AlertSession:
        return AlertSession(self.backend, connection)

    @staticmethod
    def _pk(customer_reference: Any) -> int:
        return resolve_customer_reference(customer_reference, public_only=isinstance(customer_reference, str))

    def search(self, query: str = "") -> list[dict[str, Any]]:
        self.initialize()
        term = str(query or "").strip().lower()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                sql = (
                    "SELECT c.id,c.customer_code,c.name,c.email,c.phone,c.status,c.controller_id,"
                    "c.billing_provider,c.billing_customer_id,c.billing_status,"
                    "u.username,u.active,m.account_role "
                    "FROM customers c "
                    "LEFT JOIN dashboard_users u ON u.customer_id=c.id AND u.role='customer' "
                    "LEFT JOIN customer_account_members m ON m.customer_id=c.id AND m.username=u.username "
                )
                params: tuple[Any, ...] = ()
                if term:
                    like = f"%{term}%"
                    sql += (
                        "WHERE LOWER(c.customer_code) LIKE " + ph + " OR LOWER(c.name) LIKE " + ph +
                        " OR LOWER(COALESCE(c.email,'')) LIKE " + ph +
                        " OR LOWER(COALESCE(c.billing_customer_id,'')) LIKE " + ph +
                        " OR LOWER(COALESCE(u.username,'')) LIKE " + ph + " "
                    )
                    params = (like, like, like, like, like)
                sql += "ORDER BY c.name,c.id,u.username"
                rows = session.execute(sql, params).fetchall()
            finally:
                session.close()
        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            cid = int(row["id"])
            item = grouped.setdefault(cid, {
                "id": cid,
                "customer_code": str(row["customer_code"]),
                "name": row["name"],
                "email": row["email"],
                "phone": row["phone"],
                "status": row["status"],
                "controller_id": row["controller_id"],
                "billing_provider": row["billing_provider"],
                "billing_customer_id": row["billing_customer_id"],
                "billing_status": row["billing_status"],
                "users": [],
            })
            if row["username"]:
                item["users"].append({
                    "username": row["username"],
                    "active": bool(row["active"]),
                    "account_role": row["account_role"] or "member",
                })
        return list(grouped.values())

    def detail(self, customer_reference: Any) -> dict[str, Any]:
        self.initialize()
        customer_id = self._pk(customer_reference)
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                customer = session.execute(
                    "SELECT id,customer_code,name,email,phone,status,controller_id,"
                    "billing_provider,billing_customer_id,billing_status,billing_synced_at,"
                    "created_at,updated_at FROM customers WHERE id=" + ph,
                    (customer_id,),
                ).fetchone()
                if customer is None:
                    raise ValueError("customer not found")
                users = session.execute(
                    "SELECT u.username,u.active,m.account_role,ui.email,ui.email_verified_at,"
                    "ps.must_change_password AS must_change_password "
                    "FROM dashboard_users u "
                    "LEFT JOIN customer_account_members m ON m.customer_id=u.customer_id AND m.username=u.username "
                    "LEFT JOIN customer_user_identities ui ON ui.username=u.username "
                    "LEFT JOIN customer_password_state ps ON ps.username=u.username "
                    f"WHERE u.role='customer' AND u.customer_id={ph} ORDER BY u.username",
                    (customer_id,),
                ).fetchall()
                access_rows = session.execute(
                    "SELECT ia.username,ia.instance_id,ia.permission_profile "
                    "FROM instance_access ia JOIN instances i ON i.id=ia.instance_id "
                    f"WHERE i.customer_id={ph} ORDER BY ia.username,ia.instance_id",
                    (customer_id,),
                ).fetchall()
                contracts = session.execute(
                    "SELECT c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,c.created_at,c.metadata_json,"
                    "COUNT(ic.instance_id) AS instances_used "
                    "FROM service_contracts c LEFT JOIN instance_contracts ic ON ic.contract_id=c.id "
                    f"WHERE c.customer_id={ph} GROUP BY c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,c.created_at,c.metadata_json "
                    "ORDER BY c.created_at DESC,c.id",
                    (customer_id,),
                ).fetchall()
                instances = session.execute(
                    "SELECT i.id,i.name,i.game_id,i.status,i.agent_id,ic.contract_id "
                    "FROM instances i LEFT JOIN instance_contracts ic ON ic.instance_id=i.id "
                    f"WHERE i.customer_id={ph} ORDER BY i.name,i.id",
                    (customer_id,),
                ).fetchall()
            finally:
                session.close()
        access: dict[str, dict[str, str]] = {}
        for row in access_rows:
            access.setdefault(str(row["username"]), {})[str(row["instance_id"])] = str(row["permission_profile"])
        normalized_users = []
        for row in users:
            item = dict(row)
            item["active"] = bool(row["active"])
            item["must_change_password"] = bool(row["must_change_password"])
            item["instance_access"] = access.get(str(row["username"]), {})
            normalized_users.append(item)
        normalized_contracts = []
        for row in contracts:
            item = dict(row)
            try:
                metadata = json.loads(item.pop("metadata_json", "{}") or "{}")
            except (TypeError, ValueError):
                metadata = {}
            item["resource_profile_id"] = metadata.get("resource_profile_id")
            item["resource_profile_source"] = metadata.get("resource_profile_source")
            normalized_contracts.append(item)
        return {
            "customer": dict(customer),
            "users": normalized_users,
            "contracts": normalized_contracts,
            "instances": [dict(row) for row in instances],
        }

    def create_customer(
        self,
        *,
        name: str,
        username: str,
        email: str | None = None,
        phone: str | None = None,
        controller_id: str | None = None,
        billing_provider: str | None = None,
        billing_customer_id: str | None = None,
        billing_status: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        temporary_password = self._temporary_password()
        created = self.admin.create_customer(
            name=name,
            username=username,
            password_hash=hash_password(temporary_password),
            controller_id=controller_id,
            email=email,
            phone=phone,
            billing_provider=billing_provider,
            billing_customer_id=billing_customer_id,
            billing_status=billing_status,
        )
        customer_id = int(created["id"])
        username = str(created["username"])
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                session.execute(
                    "INSERT INTO customer_account_members(customer_id,username,account_role) "
                    f"VALUES ({self.dialect.parameters(3)})",
                    (customer_id, username, "owner"),
                )
                if email:
                    session.execute(
                        "INSERT INTO customer_user_identities(username,email,email_verified_at) "
                        f"VALUES ({self.dialect.parameters(3)})",
                        (username, email, None),
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
                    f"SELECT username,role,customer_id FROM dashboard_users WHERE username={ph}",
                    (username,),
                ).fetchone()
                if row is None or row["role"] != "customer" or row["customer_id"] is None:
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
                    f"SELECT role,customer_id FROM dashboard_users WHERE username={ph}",
                    (username,),
                ).fetchone()
                if row is None or row["role"] != "customer" or row["customer_id"] is None:
                    raise ValueError("customer user not found")
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},updated_at=CURRENT_TIMESTAMP WHERE username={ph}",
                    (hash_password(new_password), username),
                )
                self._set_password_state(session, username, False)
            finally:
                session.close()

    def set_member_role(self, customer_reference: Any, username: str, account_role: str) -> None:
        self.initialize()
        customer_id = self._pk(customer_reference)
        account_role = str(account_role or "").lower()
        if account_role not in ACCOUNT_ROLES:
            raise ValueError("invalid customer account role")
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                member = session.execute(
                    "SELECT account_role FROM customer_account_members "
                    f"WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                if member is None:
                    raise ValueError("customer member not found")
                current = str(member["account_role"])
                if current == "owner" and account_role != "owner":
                    owners = session.execute(
                        f"SELECT COUNT(*) AS total FROM customer_account_members WHERE customer_id={ph} AND account_role='owner'",
                        (customer_id,),
                    ).fetchone()
                    if int(owners["total"] or 0) <= 1:
                        raise ValueError("customer must keep at least one owner")
                session.execute(
                    f"UPDATE customer_account_members SET account_role={ph} WHERE customer_id={ph} AND username={ph}",
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
        self.initialize()
        customer_id = self._pk(customer_reference)
        profile = str(permission_profile or "").strip().lower()
        if profile and profile not in INSTANCE_PROFILES:
            raise ValueError("invalid instance permission profile")
        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = self._session(connection)
            try:
                member = session.execute(
                    "SELECT 1 FROM customer_account_members "
                    f"WHERE customer_id={ph} AND username={ph}",
                    (customer_id, username),
                ).fetchone()
                instance = session.execute(
                    f"SELECT 1 FROM instances WHERE id={ph} AND customer_id={ph}",
                    (instance_id, customer_id),
                ).fetchone()
                if member is None or instance is None:
                    raise ValueError("customer member or instance not found")
                existing = session.execute(
                    f"SELECT 1 FROM instance_access WHERE username={ph} AND instance_id={ph}",
                    (username, instance_id),
                ).fetchone()
                if not profile:
                    if existing:
                        session.execute(
                            f"DELETE FROM instance_access WHERE username={ph} AND instance_id={ph}",
                            (username, instance_id),
                        )
                elif existing:
                    session.execute(
                        f"UPDATE instance_access SET permission_profile={ph} WHERE username={ph} AND instance_id={ph}",
                        (profile, username, instance_id),
                    )
                else:
                    session.execute(
                        "INSERT INTO instance_access(username,instance_id,permission_profile) "
                        f"VALUES ({self.dialect.parameters(3)})",
                        (username, instance_id, profile),
                    )
            finally:
                session.close()

    def create_contract(
        self,
        *,
        customer_code: str,
        game_id: str,
        instance_limit: int,
        contract_id: str | None = None,
        ends_at: str | None = None,
        resource_profile_id: str | None = None,
        resource_profile_source: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        return self.admin.create_contract(
            customer_id=self._pk(customer_code),
            game_id=game_id,
            instance_limit=instance_limit,
            contract_id=contract_id,
            ends_at=ends_at,
            resource_profile_id=resource_profile_id,
            resource_profile_source=resource_profile_source,
        )

    def _set_password_state(self, session: AlertSession, username: str, required: bool) -> None:
        ph = self.dialect.placeholder
        exists = session.execute(
            f"SELECT 1 FROM customer_password_state WHERE username={ph}",
            (username,),
        ).fetchone()
        value = required if self.backend.name == "postgresql" else (1 if required else 0)
        if exists:
            session.execute(
                f"UPDATE customer_password_state SET must_change_password={ph},updated_at=CURRENT_TIMESTAMP WHERE username={ph}",
                (value, username),
            )
        else:
            session.execute(
                "INSERT INTO customer_password_state(username,must_change_password) "
                f"VALUES ({self.dialect.parameters(2)})",
                (username, value),
            )

    @staticmethod
    def _temporary_password() -> str:
        return secrets.token_urlsafe(12)


__all__ = ["CustomerAdminRepository"]
