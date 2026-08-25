#!/usr/bin/env python3
"""Destructive bootstrap test for an explicitly isolated PostgreSQL database.

This test is intentionally guarded so it cannot be pointed casually at a live
Capivara database. CI runs it against an ephemeral PostgreSQL service.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_management_repository import AdminManagementRepository
from customer_management_repository import CustomerManagementRepository
from runtime_backend import backend_from_environment
from system_user_repository import SystemUserRepository
from users import hash_password


def require_isolated_target() -> None:
    if os.environ.get("CAPIVARA_ALLOW_ISOLATED_DB_TEST") != "1":
        raise RuntimeError("isolated database test requires CAPIVARA_ALLOW_ISOLATED_DB_TEST=1")
    if os.environ.get("DSM_DATABASE_DRIVER", "").strip().lower() not in {"postgres", "postgresql", "pgsql"}:
        raise RuntimeError("isolated deployment gate requires PostgreSQL")
    name = os.environ.get("DSM_DATABASE_NAME", "").strip().lower()
    if not name or "test" not in name:
        raise RuntimeError("DSM_DATABASE_NAME must contain 'test' for destructive isolated bootstrap")


def main() -> int:
    require_isolated_target()
    backend = backend_from_environment()
    if backend.name != "postgresql":
        raise AssertionError(f"unexpected backend: {backend.name}")

    # A fresh database must initialize directly at Baseline v2.
    backend.initialize()
    admin = AdminManagementRepository(backend)
    customers = CustomerManagementRepository(backend)
    system_users = SystemUserRepository(backend)

    with admin.session() as session:
        baseline = session.execute("SELECT name,checksum FROM schema_baseline").fetchall()
        existing_customers = session.execute("SELECT COUNT(*) AS total FROM customers").fetchone()
        tables = {
            str(row["table_name"])
            for row in session.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchall()
        }
    if len(baseline) != 1:
        raise AssertionError(f"expected exactly one schema_baseline row, got {len(baseline)}")
    if int(existing_customers["total"] or 0) != 0:
        raise AssertionError("isolated database was not empty before bootstrap")
    required = {
        "customers", "dashboard_users", "service_contracts", "instances",
        "instance_permission_grants", "instance_file_commands",
        "instance_console_commands", "instance_resource_commands",
        "artifact_transfers", "deleted_instance_backups", "instance_backup_clones",
        "dashboard_activity_log",
    }
    missing = sorted(required - tables)
    if missing:
        raise AssertionError("Baseline v2 missing tables: " + ", ".join(missing))

    # Canonical topology bootstrap required by Customer creation.
    with admin.session(transaction=True) as session:
        session.execute(
            "INSERT INTO nodes(id,name,role,status) VALUES (%s,%s,%s,%s)",
            ("isolated-controller-node", "Isolated Controller", "controller", "active"),
        )
        session.execute(
            "INSERT INTO controllers(id,node_id,name,status) VALUES (%s,%s,%s,%s)",
            ("isolated-controller", "isolated-controller-node", "Isolated Controller", "active"),
        )

    # First privileged user through the canonical repository.
    system_users.save(
        username="isolated-admin",
        password_hash=hash_password("Temporary-Test-Password-Only"),
        role="admin",
        scope_id=None,
        active=True,
        full_name="Isolated Test Administrator",
        corporate_email="admin.isolated@example.invalid",
        job_title="Test Administrator",
        department="CI",
        require_functional_identity=True,
    )

    # Customer creation must allocate numeric PK + public CLI code automatically.
    customer = customers.create_account(
        name="Customer Isolated Test",
        legal_name="Customer Isolated Test Ltda",
        document_type="cpf",
        document_number="12345678901",
        username="isolated-customer",
        email="customer.isolated@example.invalid",
        controller_id="isolated-controller",
        billing_provider="isolated-ci",
        billing_customer_id="billing-customer-1",
        billing_status="active",
    )
    if customer["id"] != 1 or customer["customer_code"] != "CLI-000001":
        raise AssertionError(f"unexpected Customer identity: {customer['id']} / {customer['customer_code']}")
    if not customer["must_change_password"] or not customer["temporary_password"]:
        raise AssertionError("Customer temporary-password bootstrap contract failed")

    contract = admin.create_contract(
        customer_id=customer["id"],
        game_id="minecraft",
        instance_limit=1,
        contract_id="isolated-minecraft-contract",
        resource_profile_id="standard",
        resource_profile_source="isolated-ci",
    )
    if contract["customer_id"] != 1 or contract["game_id"] != "minecraft":
        raise AssertionError("contract bootstrap failed")

    with admin.session() as session:
        stored_customer = session.execute(
            "SELECT id,customer_code,account_email,billing_provider,billing_customer_id "
            "FROM customers WHERE id=%s",
            (customer["id"],),
        ).fetchone()
        stored_user = session.execute(
            "SELECT role,customer_id,active FROM dashboard_users WHERE username=%s",
            ("isolated-customer",),
        ).fetchone()
        stored_contract = session.execute(
            "SELECT customer_id,game_id,status,instance_limit FROM service_contracts WHERE id=%s",
            (contract["id"],),
        ).fetchone()
    assert stored_customer is not None
    assert int(stored_customer["id"]) == 1
    assert stored_customer["customer_code"] == "CLI-000001"
    assert stored_customer["account_email"] == "customer.isolated@example.invalid"
    assert stored_customer["billing_provider"] == "isolated-ci"
    assert stored_customer["billing_customer_id"] == "billing-customer-1"
    assert stored_user is not None and stored_user["role"] == "customer"
    assert int(stored_user["customer_id"]) == 1 and bool(stored_user["active"])
    assert stored_contract is not None and int(stored_contract["customer_id"]) == 1
    assert stored_contract["game_id"] == "minecraft" and stored_contract["status"] == "active"

    print("postgresql_baseline_v2_isolated_deployment_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
