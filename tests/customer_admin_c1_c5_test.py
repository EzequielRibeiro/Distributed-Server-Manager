#!/usr/bin/env python3
"""Regression coverage for Customer administration stages C1 through C5."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_admin_api import (
    CUSTOMER_ADMIN_ACCESS,
    CUSTOMER_ADMIN_COLLECTION,
    CUSTOMER_ADMIN_CONTRACT,
    CUSTOMER_ADMIN_MEMBER_ROLE,
    CUSTOMER_ADMIN_PASSWORD_RESET,
    CUSTOMER_PASSWORD_CHANGE,
    dispatch_customer_admin_post,
)
from customer_admin_repository import CustomerAdminRepository
from runtime_backend import backend_from_environment
from users import verify_password


def main() -> int:
    users_html = (ROOT / "dashboard" / "web" / "users.html").read_text(encoding="utf-8")
    sidebar = (ROOT / "dashboard" / "web" / "components" / "sidebar.html").read_text(encoding="utf-8")
    customer_auth = (ROOT / "dashboard" / "web" / "customer-auth.js").read_text(encoding="utf-8")
    assert '<option value="customer">' not in users_html
    assert "Usuários do sistema" in users_html
    assert "customers.html" in sidebar
    assert "customer-change-password.html" in customer_auth

    with tempfile.TemporaryDirectory() as temp:
        backend = backend_from_environment({
            "DSM_DATABASE_DRIVER": "sqlite",
            "DSM_DATABASE": str(Path(temp) / "capivara.db"),
        })
        backend.initialize()
        repo = CustomerAdminRepository(backend)
        repo.initialize()

        with backend.transaction() as connection:
            session = repo._session(connection)
            try:
                session.execute(
                    "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                    ("controller-node", "Controller", "controller", "active"),
                )
                session.execute(
                    "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                    ("controller-1", "controller-node", "Controller", "active"),
                )
            finally:
                session.close()

        created = repo.create_customer(
            customer_id="customer-c1-c5",
            name="Customer C1-C5",
            username="owner-c1-c5",
            email="owner@example.test",
            controller_id="controller-1",
        )
        assert created["must_change_password"] is True
        assert len(created["temporary_password"]) >= 8
        assert repo.password_change_required("owner-c1-c5") is True

        detail = repo.detail("customer-c1-c5")
        assert detail["customer"]["name"] == "Customer C1-C5"
        assert detail["users"][0]["account_role"] == "owner"
        assert detail["users"][0]["must_change_password"] is True
        assert repo.search("owner@example.test")[0]["id"] == "customer-c1-c5"
        assert repo.search("owner-c1-c5")[0]["id"] == "customer-c1-c5"

        reset = repo.reset_password("owner-c1-c5")
        assert reset["must_change_password"] is True
        with backend.connect() as connection:
            session = repo._session(connection)
            try:
                user = session.execute(
                    "SELECT password_hash FROM dashboard_users WHERE username=?",
                    ("owner-c1-c5",),
                ).fetchone()
            finally:
                session.close()
        assert verify_password(reset["temporary_password"], user["password_hash"])

        repo.change_temporary_password("owner-c1-c5", "Definitiva-123")
        assert repo.password_change_required("owner-c1-c5") is False

        contract = repo.create_contract(
            customer_id="customer-c1-c5",
            game_id="dayz",
            instance_limit=2,
            contract_id="contract-c1-c5",
        )
        assert contract["instance_limit"] == 2
        assert repo.detail("customer-c1-c5")["contracts"][0]["id"] == "contract-c1-c5"

        admin = {"username": "admin", "role": "admin"}
        operator = {"username": "operator", "role": "operator"}
        customer = {"username": "owner-c1-c5", "role": "customer", "scope_id": "customer-c1-c5"}
        assert dispatch_customer_admin_post(
            CUSTOMER_ADMIN_PASSWORD_RESET, {"username": "owner-c1-c5"},
            user=operator, backend=backend,
        )[0] == 403
        assert dispatch_customer_admin_post(
            CUSTOMER_ADMIN_MEMBER_ROLE,
            {"customer_id": "customer-c1-c5", "username": "owner-c1-c5", "account_role": "owner"},
            user=admin, backend=backend,
        )[0] == 200
        assert dispatch_customer_admin_post(
            CUSTOMER_ADMIN_ACCESS,
            {"customer_id": "customer-c1-c5", "username": "owner-c1-c5", "instance_id": "missing", "permission_profile": "viewer"},
            user=admin, backend=backend,
        )[0] == 400
        assert dispatch_customer_admin_post(
            CUSTOMER_PASSWORD_CHANGE,
            {"password": "NovaSenha-456", "password_confirmation": "NovaSenha-456"},
            user=customer, backend=backend,
        )[0] == 200
        assert dispatch_customer_admin_post(
            CUSTOMER_ADMIN_CONTRACT,
            {"customer_id": "customer-c1-c5", "game_id": "rust", "instance_limit": 1},
            user=admin, backend=backend,
        )[0] == 201
        assert dispatch_customer_admin_post(
            CUSTOMER_ADMIN_COLLECTION,
            {"id": "blocked", "name": "Blocked", "username": "blocked-user"},
            user=operator, backend=backend,
        )[0] == 403

    print("customer_admin_c1_c5_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
