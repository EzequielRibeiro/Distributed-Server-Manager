#!/usr/bin/env python3
"""Focused administrative Customer management for Dashboard v2.

This module owns the read model used by Customer lookup/detail pages and the
atomic provisioning path for administrator-created Customer accounts. It keeps
Customer PKs numeric while exposing customer_code as the public reference.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

from admin_management_repository import AdminManagementRepository
from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend
from customer_billing import normalize_billing_identity
from customer_identity_repository import insert_customer
from customer_reference import resolve_customer_reference
from users import hash_password

_SEARCH_FIELDS = {"all", "name", "email", "document", "customer_code", "username"}
_DOCUMENT_TYPES = {"cpf", "cnpj", "other"}
_BILLING_STATUSES = {"pending", "active", "past_due", "suspended", "cancelled", "unlinked"}
_USERNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,127}")


class CustomerManagementRepository:
    """Persistence boundary for separated Customer administration pages."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.admin = AdminManagementRepository(backend)

    def initialize(self) -> None:
        self.backend.initialize()

    def _session(self, connection) -> AlertSession:
        return AlertSession(self.backend, connection)

    @staticmethod
    def _pk(customer_reference: Any) -> int:
        return resolve_customer_reference(
            customer_reference,
            public_only=isinstance(customer_reference, str),
        )

    @staticmethod
    def _username(value: Any) -> str:
        username = str(value or "").strip().lower()
        if not _USERNAME_RE.fullmatch(username):
            raise ValueError(
                "username must contain 2-128 letters, numbers, dot, underscore or hyphen"
            )
        return username

    @staticmethod
    def _email(value: Any) -> str:
        email = str(value or "").strip().lower()
        if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("a valid customer e-mail is required")
        if len(email) > 320:
            raise ValueError("customer e-mail is too long")
        return email

    @staticmethod
    def _document(document_type: Any, document_number: Any) -> tuple[str, str]:
        kind = str(document_type or "").strip().lower()
        raw = str(document_number or "").strip()
        if kind not in _DOCUMENT_TYPES:
            raise ValueError("document_type must be cpf, cnpj or other")
        if not raw:
            raise ValueError("document_number is required")
        if kind in {"cpf", "cnpj"}:
            number = re.sub(r"\D", "", raw)
            expected = 11 if kind == "cpf" else 14
            if len(number) != expected:
                raise ValueError(f"{kind.upper()} must contain {expected} digits")
            return kind, number
        if len(raw) > 64:
            raise ValueError("document_number is too long")
        return kind, raw

    @staticmethod
    def _search_document(value: str) -> str:
        value = str(value or "").strip()
        digits = re.sub(r"\D", "", value)
        return digits if digits else value.lower()

    def creation_options(self) -> dict[str, Any]:
        self.initialize()
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT id,name,status FROM controllers "
                    "WHERE status='active' ORDER BY name,id"
                ).fetchall()
            finally:
                session.close()
        return {
            "controllers": [dict(row) for row in rows],
            "document_types": ["cpf", "cnpj", "other"],
            "billing_statuses": sorted(_BILLING_STATUSES),
        }

    def create_account(
        self,
        *,
        name: str,
        legal_name: str | None,
        document_type: str,
        document_number: str,
        username: str,
        email: str,
        phone: str | None = None,
        controller_id: str | None = None,
        billing_provider: str | None = None,
        billing_customer_id: str | None = None,
        billing_status: str | None = None,
    ) -> dict[str, Any]:
        """Create Customer + owner login + e-mail + password state atomically."""
        self.initialize()
        name = str(name or "").strip()
        if not name:
            raise ValueError("customer name is required")
        legal_name = str(legal_name or "").strip() or None
        username = self._username(username)
        email = self._email(email)
        document_type, document_number = self._document(document_type, document_number)
        phone = str(phone or "").strip() or None
        billing = normalize_billing_identity(
            provider=billing_provider,
            customer_id=billing_customer_id,
            status=billing_status,
        )
        temporary_password = secrets.token_urlsafe(12)
        ph = self.dialect.placeholder

        with self.admin.session(transaction=True) as session:
            controller = self.admin._resolve_controller(session, controller_id)

            if session.execute(
                f"SELECT 1 FROM dashboard_users WHERE LOWER(username)=LOWER({ph})",
                (username,),
            ).fetchone() is not None:
                raise ValueError("username already exists")

            if session.execute(
                f"SELECT 1 FROM customer_user_identities WHERE LOWER(email)=LOWER({ph})",
                (email,),
            ).fetchone() is not None:
                raise ValueError("e-mail already exists")

            if session.execute(
                f"SELECT 1 FROM customers "
                f"WHERE LOWER(COALESCE(account_email,''))=LOWER({ph})",
                (email,),
            ).fetchone() is not None:
                raise ValueError("e-mail already exists")

            if billing.linked and session.execute(
                "SELECT 1 FROM customers WHERE billing_provider=" + ph +
                " AND billing_customer_id=" + ph,
                (billing.provider, billing.customer_id),
            ).fetchone() is not None:
                raise ValueError("billing customer already linked")

            identity = insert_customer(
                session,
                backend_name=self.backend.name,
                parameters=self.dialect.parameters(8),
                controller_id=str(controller["id"]),
                name=name,
                email=email,
                phone=phone,
                status="active",
                billing_provider=billing.provider,
                billing_customer_id=billing.customer_id,
                billing_status=billing.status,
            )

            session.execute(
                "UPDATE customers SET legal_name=" + ph +
                ",document_type=" + ph +
                ",document_number=" + ph +
                ",account_email=" + ph +
                ",registration_status='active'"
                ",email_verified_at=CURRENT_TIMESTAMP"
                ",updated_at=CURRENT_TIMESTAMP WHERE id=" + ph,
                (legal_name, document_type, document_number, email, identity.id),
            )

            active_value = True if self.backend.name == "postgresql" else 1
            session.execute(
                "INSERT INTO dashboard_users(username,password_hash,role,customer_id,active) "
                f"VALUES ({self.dialect.parameters(5)})",
                (
                    username,
                    hash_password(temporary_password),
                    "customer",
                    identity.id,
                    active_value,
                ),
            )
            session.execute(
                "INSERT INTO customer_account_members(customer_id,username,account_role) "
                f"VALUES ({self.dialect.parameters(3)})",
                (identity.id, username, "owner"),
            )
            session.execute(
                "INSERT INTO customer_user_identities(username,email,email_verified_at) "
                f"VALUES ({self.dialect.parameters(2)},CURRENT_TIMESTAMP)",
                (username, email),
            )
            password_required = True if self.backend.name == "postgresql" else 1
            session.execute(
                "INSERT INTO customer_password_state(username,must_change_password) "
                f"VALUES ({self.dialect.parameters(2)})",
                (username, password_required),
            )

        return {
            "id": identity.id,
            "customer_code": identity.customer_code,
            "name": name,
            "legal_name": legal_name,
            "document_type": document_type,
            "document_number": document_number,
            "username": username,
            "email": email,
            "phone": phone,
            "controller_id": str(controller["id"]),
            "status": "active",
            "registration_status": "active",
            "billing_provider": billing.provider,
            "billing_customer_id": billing.customer_id,
            "billing_status": billing.status,
            "temporary_password": temporary_password,
            "must_change_password": True,
        }

    def search(self, query: str = "", field: str = "all") -> list[dict[str, Any]]:
        self.initialize()
        term = str(query or "").strip()
        field = str(field or "all").strip().lower()
        if field not in _SEARCH_FIELDS:
            raise ValueError("invalid customer search field")
        if not term:
            return []

        ph = self.dialect.placeholder
        like = f"%{term.lower()}%"
        conditions: dict[str, tuple[str, tuple[Any, ...]]] = {
            "name": (
                "(LOWER(c.name) LIKE " + ph +
                " OR LOWER(COALESCE(c.legal_name,'')) LIKE " + ph + ")",
                (like, like),
            ),
            "email": (
                "(LOWER(COALESCE(c.account_email,c.email,'')) LIKE " + ph +
                " OR EXISTS (SELECT 1 FROM customer_user_identities i "
                "WHERE i.username=u.username AND LOWER(i.email) LIKE " + ph + "))",
                (like, like),
            ),
            "document": (
                "LOWER(COALESCE(c.document_number,'')) LIKE " + ph,
                (f"%{self._search_document(term)}%",),
            ),
            "customer_code": (
                "LOWER(c.customer_code) LIKE " + ph,
                (like,),
            ),
            "username": (
                "LOWER(COALESCE(u.username,'')) LIKE " + ph,
                (like,),
            ),
        }
        if field == "all":
            ordered = ("name", "email", "document", "customer_code", "username")
            where = " OR ".join(conditions[key][0] for key in ordered)
            params: tuple[Any, ...] = tuple(
                item for key in ordered for item in conditions[key][1]
            )
        else:
            where, params = conditions[field]

        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                rows = session.execute(
                    "SELECT c.id,c.customer_code,c.name,c.legal_name,c.email,c.account_email,c.phone,"
                    "c.document_type,c.document_number,c.status,c.registration_status,c.controller_id,"
                    "c.billing_provider,c.billing_customer_id,c.billing_status,u.username,u.active "
                    "FROM customers c "
                    "LEFT JOIN dashboard_users u ON u.customer_id=c.id AND u.role='customer' "
                    "WHERE " + where + " ORDER BY c.name,c.id,u.username",
                    params,
                ).fetchall()
            finally:
                session.close()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            customer_id = int(row["id"])
            item = grouped.setdefault(
                customer_id,
                {
                    "id": customer_id,
                    "customer_code": str(row["customer_code"]),
                    "name": row["name"],
                    "legal_name": row["legal_name"],
                    "email": row["account_email"] or row["email"],
                    "phone": row["phone"],
                    "document_type": row["document_type"],
                    "document_number": row["document_number"],
                    "status": row["status"],
                    "registration_status": row["registration_status"],
                    "controller_id": row["controller_id"],
                    "billing_provider": row["billing_provider"],
                    "billing_customer_id": row["billing_customer_id"],
                    "billing_status": row["billing_status"],
                    "users": [],
                },
            )
            if row["username"]:
                item["users"].append(
                    {
                        "username": str(row["username"]),
                        "active": bool(row["active"]),
                    }
                )
        return list(grouped.values())

    def detail(self, customer_reference: Any) -> dict[str, Any]:
        self.initialize()
        customer_id = self._pk(customer_reference)
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = self._session(connection)
            try:
                customer = session.execute(
                    "SELECT id,customer_code,controller_id,name,legal_name,email,phone,document_type,"
                    "document_number,account_email,sftp_username,status,registration_status,"
                    "email_verified_at,billing_provider,billing_customer_id,billing_status,"
                    "billing_synced_at,created_at,updated_at FROM customers WHERE id=" + ph,
                    (customer_id,),
                ).fetchone()
                if customer is None:
                    raise ValueError("customer not found")
                users = session.execute(
                    "SELECT u.username,u.active,m.account_role,i.email,i.email_verified_at,"
                    "COALESCE(ps.must_change_password,0) AS must_change_password "
                    "FROM dashboard_users u "
                    "LEFT JOIN customer_account_members m "
                    "ON m.customer_id=u.customer_id AND m.username=u.username "
                    "LEFT JOIN customer_user_identities i ON i.username=u.username "
                    "LEFT JOIN customer_password_state ps ON ps.username=u.username "
                    f"WHERE u.role='customer' AND u.customer_id={ph} ORDER BY u.username",
                    (customer_id,),
                ).fetchall()
                contracts = session.execute(
                    "SELECT c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,"
                    "c.created_at,c.updated_at,c.metadata_json,COUNT(ic.instance_id) AS instances_used "
                    "FROM service_contracts c "
                    "LEFT JOIN instance_contracts ic ON ic.contract_id=c.id "
                    f"WHERE c.customer_id={ph} "
                    "GROUP BY c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,"
                    "c.created_at,c.updated_at,c.metadata_json "
                    "ORDER BY c.created_at DESC,c.id",
                    (customer_id,),
                ).fetchall()
                instances = session.execute(
                    "SELECT i.id,i.name,i.game_id,i.status,i.agent_id,i.runtime_id,ic.contract_id "
                    "FROM instances i "
                    "LEFT JOIN instance_contracts ic ON ic.instance_id=i.id "
                    f"WHERE i.customer_id={ph} ORDER BY i.name,i.id",
                    (customer_id,),
                ).fetchall()
            finally:
                session.close()

        normalized_contracts: list[dict[str, Any]] = []
        for row in contracts:
            item = dict(row)
            try:
                metadata = json.loads(item.pop("metadata_json", "{}") or "{}")
            except (TypeError, ValueError):
                metadata = {}
            item["resource_profile_id"] = metadata.get("resource_profile_id")
            item["resource_profile_source"] = metadata.get("resource_profile_source")
            normalized_contracts.append(item)

        normalized_users = []
        for row in users:
            item = dict(row)
            item["active"] = bool(row["active"])
            item["must_change_password"] = bool(row["must_change_password"])
            normalized_users.append(item)

        return {
            "customer": dict(customer),
            "users": normalized_users,
            "contracts": normalized_contracts,
            "instances": [dict(row) for row in instances],
        }

    def create_contract(
        self,
        *,
        customer_code: str,
        game_id: str,
        instance_limit: int,
        ends_at: str | None,
        resource_profile_id: str,
        resource_profile_source: str,
    ) -> dict[str, Any]:
        return self.admin.create_contract(
            customer_id=self._pk(customer_code),
            game_id=game_id,
            instance_limit=instance_limit,
            ends_at=ends_at,
            resource_profile_id=resource_profile_id,
            resource_profile_source=resource_profile_source,
        )


__all__ = ["CustomerManagementRepository"]
