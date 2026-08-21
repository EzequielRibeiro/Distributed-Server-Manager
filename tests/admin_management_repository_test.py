#!/usr/bin/env python3
"""Regression coverage for administrative customer and contract management."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_management_repository import AdminManagementRepository
from backend import SQLiteBackend


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        os.environ["DSM_DB_BACKEND"] = "sqlite"
        db_path = Path(temp) / "capivara.db"
        backend = SQLiteBackend(db_path, ROOT / "database" / "migrations")
        backend.initialize()
        repo = AdminManagementRepository(backend)

        with repo.session(transaction=True) as session:
            session.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("controller-node", "Controller", "controller", "active"),
            )
            session.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                ("controller-1", "controller-node", "Controller", "active"),
            )

        customer = repo.create_customer(
            customer_id="customer-1",
            name="Customer 1",
            username="customer-user",
            password_hash="hash",
            controller_id="controller-1",
        )
        assert customer["id"] == "customer-1"
        assert customer["username"] == "customer-user"

        contract = repo.create_contract(
            customer_id="customer-1",
            game_id="dayz",
            instance_limit=2,
            contract_id="contract-1",
        )
        assert contract["id"] == "contract-1"
        assert contract["instance_limit"] == 2
        assert repo.customer_controller("customer-1") == "controller-1"

        with repo.session() as session:
            row = session.execute(
                "SELECT role,scope_id,active FROM dashboard_users WHERE username=?",
                ("customer-user",),
            ).fetchone()
        assert row is not None
        assert row["role"] == "customer"
        assert row["scope_id"] == "customer-1"
        assert bool(row["active"])

    print("admin_management_repository_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
