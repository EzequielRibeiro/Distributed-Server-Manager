#!/usr/bin/env python3
"""Database persistence extracted from the dashboard HTTP server."""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.network.port_allocator import (
    PortRange,
    allocate_port_profile,
)
from core.network.port_profile import PortProfile

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class DashboardRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(self, *, transaction: bool = False) -> Iterator[AlertSession]:
        context = self.backend.transaction() if transaction else self.backend.connect()
        with context as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def customer_agents(self, customer_id: str) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT a.id,a.node_id,a.name,a.status FROM agents a "
                "JOIN customers c ON c.controller_id=a.controller_id "
                f"WHERE c.id={ph} AND c.status='active' AND a.status='active' "
                "ORDER BY a.name",
                (customer_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def customer_contracts(self, customer_id: str) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT c.id,c.game_id,c.status,c.instance_limit,c.starts_at,c.ends_at,"
                "COUNT(ic.instance_id) AS instances_used FROM service_contracts c "
                "LEFT JOIN instance_contracts ic ON ic.contract_id=c.id "
                f"WHERE c.customer_id={ph} GROUP BY c.id ORDER BY c.created_at",
                (customer_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_customer_instance(
        self,
        *,
        customer_id: str,
        username: str,
        game: str,
        runtime_id: str,
        edition: str,
        variant: str | None,
        version: str,
        build: str,
        instances_root: Path,
        contract_id: str | None = None,
        selected_agent_id: str | None = None,
        network_profile: dict[str, Any] | None = None,
        occupied_ports_provider=None,
        unavailable_ports: set[int] | None = None,
        unavailable_ports_provider=None,
    ) -> dict[str, Any]:
        """Reserve ownership, contract capacity and runtime network ports."""
        self.initialize()
        ph = self.dialect.placeholder
        now = self.dialect.current_timestamp
        unavailable_ports = unavailable_ports or set()
        with self.session(transaction=True) as session:
            customer = session.execute(
                "SELECT id,controller_id,name,email,phone,status FROM customers "
                f"WHERE id={ph}",
                (customer_id,),
            ).fetchone()
            if customer is None or customer["status"] != "active":
                raise PermissionError("customer is not active")
            if contract_id:
                contract = session.execute(
                    "SELECT c.id,c.game_id,c.status,c.instance_limit,c.ends_at,"
                    "COUNT(ic.instance_id) AS instances_used "
                    "FROM service_contracts c "
                    "LEFT JOIN instance_contracts ic ON ic.contract_id=c.id "
                    f"WHERE c.id={ph} "
                    f"AND c.customer_id={ph} "
                    f"AND c.game_id={ph} "
                    "AND c.status='active' "
                    f"AND (c.ends_at IS NULL OR c.ends_at>{now}) "
                    "GROUP BY c.id "
                    "HAVING COUNT(ic.instance_id)<c.instance_limit",
                    (
                        contract_id,
                        customer["id"],
                        game,
                    ),
                ).fetchone()
            else:
                contract = session.execute(
                    "SELECT c.id,c.game_id,c.status,c.instance_limit,c.ends_at,"
                    "COUNT(ic.instance_id) AS instances_used "
                    "FROM service_contracts c "
                    "LEFT JOIN instance_contracts ic ON ic.contract_id=c.id "
                    f"WHERE c.customer_id={ph} "
                    f"AND c.game_id={ph} "
                    "AND c.status='active' "
                    f"AND (c.ends_at IS NULL OR c.ends_at>{now}) "
                    "GROUP BY c.id "
                    "HAVING COUNT(ic.instance_id)<c.instance_limit "
                    "ORDER BY c.starts_at,c.id LIMIT 1",
                    (
                        customer["id"],
                        game,
                    ),
                ).fetchone()

            if contract is None:
                if contract_id:
                    raise PermissionError(
                        "requested contract is unavailable, expired, "
                        "outside customer scope, or has no free instance slot"
                    )

                raise PermissionError(
                    "no contracted instance slot is available for this game"
                )
            if selected_agent_id:
                agent = session.execute(
                    "SELECT a.id,a.node_id,a.name,a.status,"
                    "COUNT(i.id) AS instance_count "
                    "FROM agents a "
                    "LEFT JOIN instances i ON i.agent_id=a.id "
                    f"WHERE a.id={ph} "
                    f"AND a.controller_id={ph} "
                    "AND a.status='active' "
                    "GROUP BY a.id,a.node_id,a.name,a.status",
                    (
                        selected_agent_id,
                        customer["controller_id"],
                    ),
                ).fetchone()

                if agent is None:
                    raise PermissionError(
                        "selected agent is not active or does not "
                        "belong to the customer controller"
                    )
            else:
                agent = session.execute(
                    "SELECT a.id,a.node_id,a.name,a.status,"
                    "COUNT(i.id) AS instance_count "
                    "FROM agents a "
                    "LEFT JOIN instances i ON i.agent_id=a.id "
                    f"WHERE a.controller_id={ph} "
                    "AND a.status='active' "
                    "GROUP BY a.id,a.node_id,a.name,a.status "
                    "ORDER BY instance_count,a.name,a.id LIMIT 1",
                    (
                        customer["controller_id"],
                    ),
                ).fetchone()

                if agent is None:
                    raise PermissionError(
                        "no active agent is available for "
                        "the customer controller"
                    )
            sequence_row = session.execute(
                "SELECT COUNT(*)+1 AS sequence FROM instances "
                f"WHERE customer_id={ph} AND game_id={ph}",
                (customer["id"], game),
            ).fetchone()
            sequence = int(sequence_row["sequence"])
            customer_prefix = re.sub(
                r"[^a-z0-9]+", "-", customer["id"].lower()
            ).strip("-")[:36] or "cliente"
            game_prefix = re.sub(r"[^a-z0-9]+", "-", game).strip("-")[:16]
            while True:
                instance_id = f"{customer_prefix}-{game_prefix}-{sequence:03d}"
                exists = session.execute(
                    f"SELECT 1 FROM instances WHERE id={ph}", (instance_id,)
                ).fetchone()
                if exists is None:
                    break
                sequence += 1
            game_name = {
                "dayz": "DayZ", "arma3": "Arma 3", "rust": "Rust",
                "minecraft": "Minecraft", "mindustry": "Mindustry",
            }.get(game, game.title())
            name = f"Servidor {game_name} {sequence:03d}"
            instance_path = (
                instances_root / agent["node_id"] / game / instance_id
            ).resolve()
            metadata = {
                "schema_version": 2,
                "controller_id": customer["controller_id"],
                "agent_id": agent["id"],
                "game": {"id": game},
                "runtime": {
                    "id": runtime_id, "edition": edition, "variant": variant,
                    "version": version, "build": build,
                },
                "runtime_selection": {
                    "runtime_id": runtime_id, "edition": edition,
                    "version": version, "build": build,
                },
                "owner": {"username": username},
                "customer": {
                    "id": customer["id"], "name": customer["name"],
                    "email": customer["email"], "phone": customer["phone"],
                },
            }
            metadata_path = instance_path / ".dsm" / "instance-metadata.json"
            session.execute(
                "INSERT INTO instances(id,node_id,game_id,name,status,manifest_path,"
                "metadata_json,controller_id,agent_id,customer_id,runtime_id,edition,"
                "variant,game_version,build_id) VALUES "
                f"({self.dialect.parameters(15)})",
                (instance_id, agent["node_id"], game, name, "provisioning",
                 str(metadata_path), json.dumps(metadata, ensure_ascii=False),
                 customer["controller_id"], agent["id"], customer["id"],
                 runtime_id, edition, variant, version, build),
            )
            session.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES "
                f"({self.dialect.parameters(2)})",
                (instance_id, contract["id"]),
            )
            ports: dict[str, int] = {}
            port = None

            if network_profile is not None:
                profile = PortProfile.from_mapping(
                    network_profile
                )

                if profile is None:
                    raise RuntimeError(
                        "invalid empty network profile"
                    )

                if (
                    self.backend.name
                    in {"postgresql", "mysql"}
                ):
                    session.execute(
                        "SELECT id FROM agents "
                        f"WHERE id={ph} FOR UPDATE",
                        (agent["id"],),
                    ).fetchone()

                range_rows = session.execute(
                    "SELECT protocol,start_port,end_port "
                    "FROM agent_port_ranges "
                    f"WHERE agent_id={ph} "
                    "AND status='active' "
                    "ORDER BY protocol,start_port",
                    (agent["id"],),
                ).fetchall()

                ranges = [
                    PortRange(
                        protocol=row["protocol"],
                        start_port=int(row["start_port"]),
                        end_port=int(row["end_port"]),
                    )
                    for row in range_rows
                ]

                if not ranges:
                    raise RuntimeError(
                        f"agent {agent['id']} has no active port range"
                    )

                reserved_rows = session.execute(
                    "SELECT protocol,port "
                    "FROM instance_ports "
                    f"WHERE node_id={ph}",
                    (agent["node_id"],),
                ).fetchall()

                reserved: dict[str, set[int]] = {
                    "tcp": set(),
                    "udp": set(),
                }

                for row in reserved_rows:
                    reserved[
                        row["protocol"]
                    ].add(
                        int(row["port"])
                    )

                occupied: dict[str, set[int]] = {
                    "tcp": set(),
                    "udp": set(),
                }

                provider = occupied_ports_provider

                if (
                    provider is None
                    and unavailable_ports_provider is not None
                ):
                    legacy = set(
                        unavailable_ports_provider()
                    )

                    def provider(
                        agent_id,
                        node_id,
                        protocol,
                        start_port,
                        end_port,
                    ):
                        if protocol != "udp":
                            return set()

                        return {
                            value
                            for value in legacy
                            if start_port <= value <= end_port
                        }

                if provider is None:
                    raise RuntimeError(
                        "operating-system port inspection "
                        "provider is required"
                    )

                for item in ranges:
                    if item.protocol not in profile.protocols:
                        continue

                    occupied[
                        item.protocol
                    ].update(
                        provider(
                            agent["id"],
                            agent["node_id"],
                            item.protocol,
                            item.start_port,
                            item.end_port,
                        )
                    )

                allocation = allocate_port_profile(
                    profile,
                    ranges,
                    reserved=reserved,
                    occupied=occupied,
                )

                ports = dict(
                    allocation.ports
                )

                requirements = {
                    requirement.name: requirement
                    for requirement in profile.ports
                }

                for name, reserved_port in ports.items():
                    requirement = requirements[
                        name
                    ]

                    session.execute(
                        "INSERT INTO instance_ports("
                        "instance_id,node_id,name,protocol,"
                        "port,bind_address"
                        ") VALUES "
                        f"({self.dialect.parameters(6)})",
                        (
                            instance_id,
                            agent["node_id"],
                            name,
                            requirement.protocol,
                            reserved_port,
                            requirement.bind_address,
                        ),
                    )

                metadata["network"] = {
                    "ports": ports,
                }

                session.execute(
                    "UPDATE instances "
                    f"SET metadata_json={ph} "
                    f"WHERE id={ph}",
                    (
                        json.dumps(
                            metadata,
                            ensure_ascii=False,
                        ),
                        instance_id,
                    ),
                )

                port = ports.get(
                    "game"
                )

        return {
            "instance_id": instance_id, "name": name,
            "instance_path": instance_path, "metadata_path": metadata_path,
            "metadata": metadata, "agent_id": agent["id"],
            "node_id": agent["node_id"], "contract_id": contract["id"],
            "game_port": port,
            "ports": ports,
        }

    def update_instance_status(self, instance_id: str, status: str) -> int:
        with self.session(transaction=True) as session:
            cursor = session.execute(
                f"UPDATE instances SET status={self.dialect.placeholder} "
                f"WHERE id={self.dialect.placeholder}",
                (status, instance_id),
            )
        return cursor.rowcount

    def instance_context(self, instance_id: str) -> dict[str, Any] | None:
        with self.session() as session:
            row = session.execute(
                "SELECT controller_id,agent_id,node_id,customer_id FROM instances "
                f"WHERE id={self.dialect.placeholder}",
                (instance_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def instance_port(self, instance_id: str, name="game", protocol="udp") -> int | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT port FROM instance_ports "
                f"WHERE instance_id={ph} AND name={ph} AND protocol={ph}",
                (instance_id, name, protocol),
            ).fetchone()
        return None if row is None else int(row["port"])

    def instance_ports(self, instance_id: str) -> dict[str, int]:
        ph = self.dialect.placeholder

        with self.session() as session:
            rows = session.execute(
                "SELECT name,port "
                "FROM instance_ports "
                f"WHERE instance_id={ph} "
                "ORDER BY name",
                (instance_id,),
            ).fetchall()

        return {
            row["name"]: int(row["port"])
            for row in rows
        }

    def permission_profile(self, username: str, instance_id: str) -> str | None:
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT permission_profile FROM instance_access "
                f"WHERE username={ph} AND instance_id={ph}",
                (username, instance_id),
            ).fetchone()
        return None if row is None else row["permission_profile"]

    def write_audit(self, username: str, instance_id: str | None,
                    action: str, result: str, details: str | None) -> None:
        with self.session(transaction=True) as session:
            session.execute(
                "INSERT INTO audit_log(username,instance_id,action,result,details) "
                f"VALUES ({self.dialect.parameters(5)})",
                (username, instance_id, action, result, details),
            )

    def delete_instance(self, instance_id: str) -> int:
        with self.session(transaction=True) as session:
            cursor = session.execute(
                f"DELETE FROM instances WHERE id={self.dialect.placeholder}",
                (instance_id,),
            )
        return cursor.rowcount

    def registered_instances(self) -> set[tuple[str, str, str]]:
        with self.session() as session:
            rows = session.execute("SELECT id,node_id,game_id FROM instances").fetchall()
        return {(row["node_id"], row["game_id"], row["id"]) for row in rows}

    def load_users(self) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.execute(
                "SELECT username,password_hash,role,scope_id,active "
                "FROM dashboard_users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_user(self, username: str, password_hash: str, role: str,
                  scope_id: str | None, active: bool) -> None:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            exists = session.execute(
                f"SELECT 1 FROM dashboard_users WHERE username={ph}",
                (username,),
            ).fetchone()
            active_value = active if self.backend.name == "postgresql" else int(active)
            if exists is None:
                session.execute(
                    "INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) "
                    f"VALUES ({self.dialect.parameters(5)})",
                    (username, password_hash, role, scope_id, active_value),
                )
            else:
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},role={ph},"
                    f"scope_id={ph},active={ph},updated_at={self.dialect.current_timestamp} "
                    f"WHERE username={ph}",
                    (password_hash, role, scope_id, active_value, username),
                )

    def delete_user(self, username: str) -> int:
        with self.session(transaction=True) as session:
            cursor = session.execute(
                f"DELETE FROM dashboard_users WHERE username={self.dialect.placeholder}",
                (username,),
            )
        return cursor.rowcount

    def retry_instance(self, instance_id: str) -> dict[str, Any] | None:
        with self.session() as session:
            row = session.execute(
                "SELECT id,node_id,game_id,agent_id,runtime_id,edition,"
                "game_version,build_id,status FROM instances WHERE id="
                + self.dialect.placeholder,
                (instance_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def reserve_retry(
        self,
        instance_id: str,
        node_id: str,
        game_id: str,
    ) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            row = session.execute(
                "SELECT id,node_id,game_id,agent_id,runtime_id,edition,"
                f"game_version,build_id,status FROM instances WHERE id={ph}",
                (instance_id,),
            ).fetchone()
            if row is None:
                raise ValueError("instance is not registered")
            result = dict(row)
            if result["node_id"] != node_id or result["game_id"] != game_id:
                raise ValueError("instance identity does not match database")
            if result["status"] not in {"failed", "pending_steam_auth"}:
                raise ValueError(
                    "only a failed or pending Steam authentication provision can be retried"
                )
            session.execute(
                "UPDATE instances SET status='queued',"
                f"updated_at={self.dialect.current_timestamp} WHERE id={ph}",
                (instance_id,),
            )
        return result

    def reconcile_instance_status(self, instance_id: str, status: str) -> int:
        ph = self.dialect.placeholder
        protected = (
            "queued", "provisioning", "installing",
            "pending_steam_auth", "failed",
        )
        with self.session(transaction=True) as session:
            cursor = session.execute(
                f"UPDATE instances SET status={ph} WHERE id={ph} AND status<>{ph} "
                f"AND status NOT IN ({self.dialect.parameters(len(protected))})",
                (status, instance_id, status, *protected),
            )
        return cursor.rowcount

    def scope_options(self) -> dict[str, list[dict[str, Any]]]:
        with self.session() as session:
            controllers = session.execute(
                "SELECT id,name,status FROM controllers ORDER BY name"
            ).fetchall()
            customers = session.execute(
                "SELECT id,name,status FROM customers ORDER BY name"
            ).fetchall()
        return {
            "controllers": [dict(row) for row in controllers],
            "customers": [dict(row) for row in customers],
        }

    def close(self) -> None:
        self.backend.close()
