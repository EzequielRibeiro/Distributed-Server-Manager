#!/usr/bin/env python3
"""Test-only registry topology fixture."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from admin_management_repository import AdminManagementRepository

_FIXTURE_LOGO = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E"
    "%3Crect width='128' height='128' rx='24' fill='%230f172a'/%3E"
    "%3Cpath d='M64 18 103 93H25Z' fill='%2338bdf8'/%3E"
    "%3Ccircle cx='64' cy='72' r='17' fill='%23020617'/%3E%3C/svg%3E"
)


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt${2**14}$8$1${salt.hex()}${digest.hex()}"


def create_registry_fixture(root: Path, registry_module: Any, database_path: Any) -> dict[str, object]:
    """Create the historical test topology without exposing it in production code."""
    instance_path = root / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
    metadata_dir = instance_path / ".dsm"
    metadata_path = metadata_dir / "instance-metadata.json"
    repository = registry_module._repository(database_path)
    repository.initialize()

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
            password_hash=_password_hash("Aurora@2026!"),
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
        "logo_url": _FIXTURE_LOGO,
    }

    with repository.transaction() as session:
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
            "id": "cliente-demo", "node_id": "DemoNode", "game_id": "minecraft",
            "name": "Servidor Aurora", "status": "offline",
            "manifest_path": str(metadata_path),
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "controller_id": "controller-demo", "agent_id": "agent-demo",
            "customer_id": customer_id,
        })
        for contract_id, game_id, metadata_json in (
            ("aurora-minecraft-001", "minecraft", '{"demo":true}'),
            ("aurora-dayz-001", "dayz", '{"demo":true,"service":"DayZ"}'),
        ):
            repository._upsert(session, "service_contracts", "id", {
                "id": contract_id, "customer_id": customer_id,
                "game_id": game_id, "status": "active", "instance_limit": 1,
                "metadata_json": metadata_json,
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

    metadata_dir.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, metadata_path)
    return {
        "created": True,
        "controller_id": "controller-demo",
        "agent_id": "agent-demo",
        "customer_id": customer_id,
        "customer_code": customer_code,
        "instance_id": "cliente-demo",
        "instance": str(instance_path),
        "metadata": str(metadata_path),
    }
