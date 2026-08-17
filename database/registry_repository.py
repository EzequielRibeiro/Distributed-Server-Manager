#!/usr/bin/env python3
"""Backend-independent instance ownership registry persistence."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class RegistryRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def transaction(self) -> Iterator[AlertSession]:
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def _upsert(
        self,
        session: AlertSession,
        table: str,
        key: str,
        values: Mapping[str, Any],
    ) -> None:
        ph = self.dialect.placeholder
        exists = session.execute(
            f"SELECT 1 FROM {table} WHERE {key}={ph}",
            (values[key],),
        ).fetchone()
        if exists is None:
            columns = tuple(values)
            session.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES "
                f"({self.dialect.parameters(len(columns))})",
                tuple(values[column] for column in columns),
            )
            return
        updates = [column for column in values if column != key]
        session.execute(
            f"UPDATE {table} SET "
            + ",".join(f"{column}={ph}" for column in updates)
            + f" WHERE {key}={ph}",
            tuple(values[column] for column in updates) + (values[key],),
        )

    def create_aurora(
        self,
        *,
        password_hash: str,
        manifest_path: str,
        metadata_json: str,
    ) -> None:
        self.initialize()
        with self.transaction() as session:
            self._upsert(session, "nodes", "id", {
                "id": "controller-demo", "name": "Controlador Demo",
                "role": "controller", "status": "active",
            })
            self._upsert(session, "nodes", "id", {
                "id": "DemoNode", "name": "Agente Aurora",
                "role": "agent", "status": "active",
            })
            self._upsert(session, "controllers", "id", {
                "id": "controller-demo", "node_id": "controller-demo",
                "name": "Controlador Demo", "status": "active",
            })
            self._upsert(session, "agents", "id", {
                "id": "agent-demo", "controller_id": "controller-demo",
                "node_id": "DemoNode", "name": "Agente Aurora", "status": "active",
            })
            self._upsert(session, "customers", "id", {
                "id": "CLI-DEMO-001", "controller_id": "controller-demo",
                "name": "Aurora Games Ltda.", "email": "contato@example.invalid",
                "phone": "+55 11 0000-0000", "status": "active",
            })
            ph = self.dialect.placeholder
            if session.execute(
                "SELECT 1 FROM dashboard_users WHERE username=" + ph,
                ("aurora",),
            ).fetchone() is None:
                session.execute(
                    "INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) "
                    f"VALUES ({self.dialect.parameters(4)},1)",
                    ("aurora", password_hash, "customer", "CLI-DEMO-001"),
                )
            self._upsert(session, "instances", "id", {
                "id": "cliente-demo", "node_id": "DemoNode", "game_id": "minecraft",
                "name": "Servidor Aurora", "status": "offline",
                "manifest_path": manifest_path, "metadata_json": metadata_json,
                "controller_id": "controller-demo", "agent_id": "agent-demo",
                "customer_id": "CLI-DEMO-001",
            })
            for contract_id, game_id, metadata in (
                ("aurora-minecraft-001", "minecraft", '{"demo":true}'),
                ("aurora-dayz-001", "dayz", '{"demo":true,"service":"DayZ"}'),
            ):
                self._upsert(session, "service_contracts", "id", {
                    "id": contract_id, "customer_id": "CLI-DEMO-001",
                    "game_id": game_id, "status": "active",
                    "instance_limit": 1, "metadata_json": metadata,
                })
            session.execute(
                "DELETE FROM instance_contracts WHERE instance_id=" + ph,
                ("cliente-demo",),
            )
            session.execute(
                "INSERT INTO instance_contracts(instance_id,contract_id) VALUES "
                f"({self.dialect.parameters(2)})",
                ("cliente-demo", "aurora-minecraft-001"),
            )

    def get_instance(self, instance_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    "SELECT id,node_id,game_id,name FROM instances WHERE id="
                    + self.dialect.placeholder,
                    (instance_id,),
                ).fetchone()
            finally:
                session.close()
        return None if row is None else dict(row)

    def delete_instance(self, instance_id: str) -> None:
        self.initialize()
        with self.transaction() as session:
            session.execute(
                "DELETE FROM instances WHERE id=" + self.dialect.placeholder,
                (instance_id,),
            )

    def close(self) -> None:
        self.backend.close()
