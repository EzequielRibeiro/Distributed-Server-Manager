#!/usr/bin/env python3
"""Create strictly-owned Capivara DSM instances."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from contextlib import closing
from pathlib import Path

import manager as database
from backend import DatabaseBackend, DatabaseConfig
from backend_factory import create_backend
from registry_repository import RegistryRepository


AURORA_LOGO = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E"
    "%3Crect width='128' height='128' rx='24' fill='%230f172a'/%3E"
    "%3Cpath d='M64 18 103 93H25Z' fill='%2338bdf8'/%3E"
    "%3Ccircle cx='64' cy='72' r='17' fill='%23020617'/%3E%3C/svg%3E"
)


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${2**14}$8$1${salt.hex()}${digest.hex()}"


def create_aurora(root: Path, database_path: Path) -> dict[str, object]:
    database.initialize(database_path)
    instance_path = root / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
    metadata = {
        "schema_version": 1,
        "controller_id": "controller-demo",
        "agent_id": "agent-demo",
        "display_name": "Servidor Aurora",
        "owner": {"name": "Marina Souza", "username": "marina.demo"},
        "customer": {
            "id": "CLI-DEMO-001",
            "name": "Aurora Games Ltda.",
            "email": "contato@example.invalid",
            "phone": "+55 11 0000-0000",
        },
        "logo_url": AURORA_LOGO,
    }

    with closing(database.connect(database_path)) as connection:
        with connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,status=excluded.status",
                ("controller-demo", "Controlador Demo", "controller", "active"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,status=excluded.status",
                ("DemoNode", "Agente Aurora", "agent", "active"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET node_id=excluded.node_id,name=excluded.name,status=excluded.status",
                ("controller-demo", "controller-demo", "Controlador Demo", "active"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET controller_id=excluded.controller_id,node_id=excluded.node_id,name=excluded.name,status=excluded.status",
                ("agent-demo", "controller-demo", "DemoNode", "Agente Aurora", "active"),
            )
            connection.execute(
                "INSERT INTO customers(id,controller_id,name,email,phone,status) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET controller_id=excluded.controller_id,name=excluded.name,email=excluded.email,phone=excluded.phone,status=excluded.status",
                ("CLI-DEMO-001", "controller-demo", "Aurora Games Ltda.", "contato@example.invalid", "+55 11 0000-0000", "active"),
            )
            existing_aurora = connection.execute(
                "SELECT username FROM dashboard_users WHERE username='aurora'"
            ).fetchone()
            if not existing_aurora:
                connection.execute(
                    "INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) VALUES (?,?,?,?,1)",
                    ("aurora", password_hash("Aurora@2026!"), "customer", "CLI-DEMO-001"),
                )
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,manifest_path,metadata_json,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "node_id=excluded.node_id,game_id=excluded.game_id,name=excluded.name,status=excluded.status,"
                "manifest_path=excluded.manifest_path,metadata_json=excluded.metadata_json,"
                "controller_id=excluded.controller_id,agent_id=excluded.agent_id,customer_id=excluded.customer_id",
                (
                    "cliente-demo", "DemoNode", "minecraft", "Servidor Aurora", "offline",
                    str(instance_path / ".dsm" / "instance-metadata.json"),
                    json.dumps(metadata, ensure_ascii=False),
                    "controller-demo", "agent-demo", "CLI-DEMO-001",
                ),
            )
            connection.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id,"
                "game_id=excluded.game_id,status=excluded.status,instance_limit=excluded.instance_limit",
                ("aurora-minecraft-001", "CLI-DEMO-001", "minecraft", "active", 1, '{"demo":true}'),
            )
            connection.execute("DELETE FROM instance_contracts WHERE instance_id=?", ("cliente-demo",))
            connection.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES (?,?)",
                ("cliente-demo", "aurora-minecraft-001"),
            )
            connection.execute(
                "INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit,metadata_json) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id,"
                "game_id=excluded.game_id,status=excluded.status,instance_limit=excluded.instance_limit",
                ("aurora-dayz-001", "CLI-DEMO-001", "dayz", "active", 1, '{"demo":true,"service":"DayZ"}'),
            )

    metadata_dir = instance_path / ".dsm"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_dir / "instance-metadata.json"
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, metadata_path)
    return {
        "created": True,
        "controller_id": "controller-demo",
        "agent_id": "agent-demo",
        "customer_id": "CLI-DEMO-001",
        "instance_id": "cliente-demo",
        "instance": str(instance_path),
        "metadata": str(metadata_path),
    }


def purge_orphan_instance(root: Path, database_path: Path, instance_id: str) -> dict[str, object]:
    """Remove somente um cadastro sem diretório físico de instância.

    Esta operação é destinada à limpeza de registros antigos deixados por
    versões anteriores do DSM. Instâncias existentes devem ser removidas pela
    área administrativa, que executa parada controlada e oferece backup final.
    """
    if not instance_id or not all(part not in instance_id for part in ("/", "\\", "..")):
        raise ValueError("invalid instance identifier")

    database.initialize(database_path)
    with closing(database.connect(database_path)) as connection:
        row = connection.execute(
            "SELECT id,node_id,game_id,name FROM instances WHERE id=?", (instance_id,)
        ).fetchone()
        if not row:
            raise ValueError("instance is not registered")
        instance_path = root / "instances" / row["node_id"] / row["game_id"] / row["id"]
        if instance_path.exists():
            raise ValueError(
                "instance has a local directory; use the instance administration danger zone instead"
            )
        runtime_path = root / "runtime" / "resources" / row["node_id"] / row["game_id"] / row["id"]
        with connection:
            connection.execute("DELETE FROM instances WHERE id=?", (instance_id,))

    if runtime_path.is_dir():
        import shutil
        shutil.rmtree(runtime_path)
    return {
        "purged": True,
        "instance_id": instance_id,
        "name": row["name"],
        "runtime_removed": runtime_path.exists() is False,
    }


def _repository(target: Path | DatabaseBackend) -> RegistryRepository:
    if isinstance(target, DatabaseBackend):
        return RegistryRepository(target)
    return RegistryRepository(create_backend(DatabaseConfig(
        driver="sqlite", database=str(Path(target).expanduser().resolve())
    )))


def create_aurora(
    root: Path,
    database_path: Path | DatabaseBackend,
) -> dict[str, object]:
    """Create the Aurora hierarchy through RegistryRepository."""
    instance_path = root / "instances" / "DemoNode" / "minecraft" / "cliente-demo"
    metadata = {
        "schema_version": 1,
        "controller_id": "controller-demo",
        "agent_id": "agent-demo",
        "display_name": "Servidor Aurora",
        "owner": {"name": "Marina Souza", "username": "marina.demo"},
        "customer": {
            "id": "CLI-DEMO-001", "name": "Aurora Games Ltda.",
            "email": "contato@example.invalid", "phone": "+55 11 0000-0000",
        },
        "logo_url": AURORA_LOGO,
    }
    metadata_dir = instance_path / ".dsm"
    metadata_path = metadata_dir / "instance-metadata.json"
    repository = _repository(database_path)
    repository.create_aurora(
        password_hash=password_hash("Aurora@2026!"),
        manifest_path=str(metadata_path),
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    metadata_dir.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, metadata_path)
    return {
        "created": True, "controller_id": "controller-demo",
        "agent_id": "agent-demo", "customer_id": "CLI-DEMO-001",
        "instance_id": "cliente-demo", "instance": str(instance_path),
        "metadata": str(metadata_path),
    }


def purge_orphan_instance(
    root: Path,
    database_path: Path | DatabaseBackend,
    instance_id: str,
) -> dict[str, object]:
    """Remove a registry row only when no local instance directory exists."""
    if not instance_id or not all(
        part not in instance_id for part in ("/", "\\", "..")
    ):
        raise ValueError("invalid instance identifier")
    repository = _repository(database_path)
    row = repository.get_instance(instance_id)
    if row is None:
        raise ValueError("instance is not registered")
    instance_path = root / "instances" / row["node_id"] / row["game_id"] / row["id"]
    if instance_path.exists():
        raise ValueError(
            "instance has a local directory; use the instance administration danger zone instead"
        )
    runtime_path = root / "runtime" / "resources" / row["node_id"] / row["game_id"] / row["id"]
    repository.delete_instance(instance_id)
    if runtime_path.is_dir():
        import shutil
        shutil.rmtree(runtime_path)
    return {
        "purged": True, "instance_id": instance_id, "name": row["name"],
        "runtime_removed": not runtime_path.exists(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capivara DSM ownership registry")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("DSM_ROOT", "/opt/dsm")))
    parser.add_argument("--database", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("create-aurora", help="create the fictitious Aurora hierarchy")
    purge = subcommands.add_parser("purge-orphan", help="remove an orphan instance record without a local directory")
    purge.add_argument("instance_id")
    args = parser.parse_args()
    root = args.root.resolve()
    database_path = (args.database or root / "data" / "capivara.db").resolve()
    if args.command == "create-aurora":
        payload = create_aurora(root, database_path)
    else:
        payload = purge_orphan_instance(root, database_path, args.instance_id)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
