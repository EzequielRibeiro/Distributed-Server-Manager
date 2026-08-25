#!/usr/bin/env python3
"""Baseline v2 demonstration hierarchy used by registry tests and demo CLI."""

from __future__ import annotations

import json
from typing import Any

from admin_management_repository import AdminManagementRepository
from registry_repository import RegistryRepository


def create_aurora_demo(
    repository: RegistryRepository,
    *,
    password_hash: str,
    manifest_path: str,
    logo_url: str,
) -> dict[str, Any]:
    """Create/update the fictitious Aurora hierarchy without textual PKs."""
    repository.initialize()

    # Infrastructure identity is deterministic and idempotent.
    with repository.transaction() as session:
        repository._upsert(session, "nodes", "id", {
            "id": "controller-demo", "name": "Controlador Demo",
            "role": "controller", "status": "active",
        })
        repository._upsert(session, "nodes", "id", {
            "id": "DemoNode", "name": "Agente Aurora",
            "role": "agent", "status": "active",
        })
        repository._upsert(session, "controllers", "id", {
            "id": "controller-demo", "node_id": "controller-demo",
            "name": "Controlador Demo", "status": "active",
        })
        repository._upsert(session, "agents", "id", {
            "id": "agent-demo", "controller_id": "controller-demo",
            "node_id": "DemoNode", "name": "Agente Aurora", "status": "active",
        })
        ph = repository.dialect.placeholder
        existing = session.execute(
            "SELECT c.id,c.customer_code FROM customers c "
            "JOIN dashboard_users u ON u.customer_id=c.id "
            f"WHERE u.username={ph} AND u.role='customer'",
            ("aurora",),
        ).fetchone()

    if existing is None:
        created = AdminManagementRepository(repository.backend).create_customer(
            name="Aurora Games Ltda.",
            username="aurora",
            password_hash=password_hash,
            controller_id="controller-demo",
            email="contato@example.invalid",
            phone="+55 11 0000-0000",
        )
        customer_id = int(created["id"])
        customer_code = str(created["customer_code"])
    else:
        customer_id = int(existing["id"])
        customer_code = str(existing["customer_code"])

    metadata = {
        "schema_version": 2,
        "controller_id": "controller-demo",
        "agent_id": "agent-demo",
        "display_name": "Servidor Aurora",
        "owner": {"name": "Marina Souza", "username": "marina.demo"},
        "customer": {
            "id": customer_code,
            "customer_code": customer_code,
            "name": "Aurora Games Ltda.",
            "email": "contato@example.invalid",
            "phone": "+55 11 0000-0000",
        },
        "logo_url": logo_url,
    }

    with repository.transaction() as session:
        repository._upsert(session, "customers", "id", {
            "id": customer_id,
            "controller_id": "controller-demo",
            "name": "Aurora Games Ltda.",
            "email": "contato@example.invalid",
            "phone": "+55 11 0000-0000",
            "status": "active",
        })
        ph = repository.dialect.placeholder
        member = session.execute(
            "SELECT 1 FROM customer_account_members "
            f"WHERE customer_id={ph} AND username={ph}",
            (customer_id, "aurora"),
        ).fetchone()
        if member is None:
            session.execute(
                "INSERT INTO customer_account_members(customer_id,username,account_role) "
                f"VALUES ({repository.dialect.parameters(3)})",
                (customer_id, "aurora", "owner"),
            )

        repository._upsert(session, "instances", "id", {
            "id": "cliente-demo",
            "node_id": "DemoNode",
            "game_id": "minecraft",
            "name": "Servidor Aurora",
            "status": "offline",
            "manifest_path": manifest_path,
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "controller_id": "controller-demo",
            "agent_id": "agent-demo",
            "customer_id": customer_id,
        })
        repository._upsert(session, "service_contracts", "id", {
            "id": "aurora-minecraft-001",
            "customer_id": customer_id,
            "game_id": "minecraft",
            "status": "active",
            "instance_limit": 1,
            "metadata_json": '{"demo":true}',
        })
        repository._upsert(session, "service_contracts", "id", {
            "id": "aurora-dayz-001",
            "customer_id": customer_id,
            "game_id": "dayz",
            "status": "active",
            "instance_limit": 1,
            "metadata_json": '{"demo":true,"service":"DayZ"}',
        })
        session.execute(
            f"DELETE FROM instance_contracts WHERE instance_id={ph}",
            ("cliente-demo",),
        )
        session.execute(
            "INSERT INTO instance_contracts(instance_id,contract_id) "
            f"VALUES ({repository.dialect.parameters(2)})",
            ("cliente-demo", "aurora-minecraft-001"),
        )

    return {
        "customer_id": customer_id,
        "customer_code": customer_code,
        "metadata": metadata,
    }


__all__ = ["create_aurora_demo"]
