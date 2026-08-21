#!/usr/bin/env python3
"""Administrative persistence for customers, contracts and Agent resolution."""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,127}")
_GAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,63}")


class AdminManagementRepository:
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

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        normalized = str(value or "").strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError(f"invalid {label}")
        return normalized

    def _resolve_controller(self, session: AlertSession, controller_id: str | None):
        ph = self.dialect.placeholder
        if controller_id:
            controller_id = self._identifier(controller_id, "controller_id")
            row = session.execute(
                "SELECT id,name,status FROM controllers "
                f"WHERE id={ph}",
                (controller_id,),
            ).fetchone()
            if row is None or str(row["status"]).lower() != "active":
                raise ValueError("controller not found or inactive")
            return row

        rows = session.execute(
            "SELECT id,name,status FROM controllers "
            "WHERE status='active' ORDER BY id"
        ).fetchall()
        if not rows:
            raise ValueError("no active controller is registered")
        if len(rows) != 1:
            raise ValueError("multiple active controllers; use --controller")
        return rows[0]

    def create_customer(
        self,
        *,
        customer_id: str,
        name: str,
        username: str,
        password_hash: str,
        controller_id: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> dict[str, Any]:
        customer_id = self._identifier(customer_id, "customer_id")
        username = self._identifier(username, "username").lower()
        name = str(name or "").strip()
        if not name:
            raise ValueError("customer name is required")
        if not password_hash:
            raise ValueError("password hash is required")

        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            controller = self._resolve_controller(session, controller_id)
            if session.execute(
                f"SELECT 1 FROM customers WHERE id={ph}", (customer_id,)
            ).fetchone() is not None:
                raise ValueError("customer already exists")
            if session.execute(
                f"SELECT 1 FROM dashboard_users WHERE username={ph}", (username,)
            ).fetchone() is not None:
                raise ValueError("username already exists")

            session.execute(
                "INSERT INTO customers(id,controller_id,name,email,phone,status) "
                f"VALUES ({self.dialect.parameters(6)})",
                (customer_id, controller["id"], name, email, phone, "active"),
            )
            active_value = True if self.backend.name == "postgresql" else 1
            session.execute(
                "INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) "
                f"VALUES ({self.dialect.parameters(5)})",
                (username, password_hash, "customer", customer_id, active_value),
            )

        return {
            "id": customer_id,
            "name": name,
            "username": username,
            "controller_id": str(controller["id"]),
            "status": "active",
        }

    def create_contract(
        self,
        *,
        customer_id: str,
        game_id: str,
        instance_limit: int = 1,
        contract_id: str | None = None,
        ends_at: str | None = None,
    ) -> dict[str, Any]:
        customer_id = self._identifier(customer_id, "customer_id")
        game_id = str(game_id or "").strip().lower()
        if not _GAME_RE.fullmatch(game_id):
            raise ValueError("invalid game_id")
        try:
            instance_limit = int(instance_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("instances must be a positive integer") from exc
        if instance_limit <= 0:
            raise ValueError("instances must be a positive integer")
        if contract_id:
            contract_id = self._identifier(contract_id, "contract_id")
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", customer_id.lower()).strip("-")[:36]
            contract_id = f"contract-{slug}-{game_id}-{uuid.uuid4().hex[:8]}"

        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            customer = session.execute(
                "SELECT id,status FROM customers "
                f"WHERE id={ph}",
                (customer_id,),
            ).fetchone()
            if customer is None or str(customer["status"]).lower() != "active":
                raise ValueError("customer not found or inactive")
            if session.execute(
                f"SELECT 1 FROM service_contracts WHERE id={ph}", (contract_id,)
            ).fetchone() is not None:
                raise ValueError("contract already exists")

            session.execute(
                "INSERT INTO service_contracts("
                "id,customer_id,game_id,status,instance_limit,ends_at"
                ") VALUES (" + self.dialect.parameters(6) + ")",
                (contract_id, customer_id, game_id, "active", instance_limit, ends_at),
            )

        return {
            "id": contract_id,
            "customer_id": customer_id,
            "game_id": game_id,
            "status": "active",
            "instance_limit": instance_limit,
            "ends_at": ends_at,
        }

    def customer_controller(self, customer_id: str) -> str:
        customer_id = self._identifier(customer_id, "customer_id")
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT controller_id,status FROM customers "
                f"WHERE id={ph}",
                (customer_id,),
            ).fetchone()
        if row is None or str(row["status"]).lower() != "active":
            raise ValueError("customer not found or inactive")
        return str(row["controller_id"])

    def resolve_agent(self, controller_id: str, selector: str) -> dict[str, Any]:
        selector = str(selector or "").strip()
        if not selector:
            raise ValueError("agent selector is required")
        ph = self.dialect.placeholder
        with self.session() as session:
            rows = session.execute(
                "SELECT a.id,a.node_id,a.name,a.status,ari.address,ari.health_status "
                "FROM agents a LEFT JOIN agent_runtime_inventory ari ON ari.agent_id=a.id "
                f"WHERE a.controller_id={ph} ORDER BY a.id",
                (controller_id,),
            ).fetchall()

        direct = [row for row in rows if str(row["id"]) == selector]
        address = [row for row in rows if str(row["address"] or "").strip() == selector]
        matches = direct or address
        if not matches:
            raise ValueError("agent not found for this customer controller")
        if len(matches) > 1:
            raise ValueError("agent selector is ambiguous; use the Agent ID")
        return dict(matches[0])

    def begin_instance_delete(self, instance_id: str) -> dict[str, Any]:
        """Mark one instance for Agent-confirmed removal."""
        instance_id = self._identifier(instance_id, "instance_id")
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            row = session.execute(
                "SELECT i.id,i.agent_id,i.customer_id,i.status,ic.contract_id "
                "FROM instances i LEFT JOIN instance_contracts ic ON ic.instance_id=i.id "
                f"WHERE i.id={ph}",
                (instance_id,),
            ).fetchone()
            if row is None:
                raise ValueError("instance not found")
            agent = session.execute(
                f"SELECT status FROM agents WHERE id={ph}", (row["agent_id"],)
            ).fetchone()
            if agent is None or str(agent["status"] or "").lower() != "active":
                raise RuntimeError("owning Agent must be active before deletion can be queued")
            previous_status = str(row["status"] or "")
            if previous_status != "deleting":
                session.execute(
                    f"UPDATE instances SET status={ph} WHERE id={ph}",
                    ("deleting", instance_id),
                )
        return {
            "instance_id": instance_id,
            "agent_id": str(row["agent_id"]),
            "customer_id": str(row["customer_id"]),
            "contract_id": None if row["contract_id"] is None else str(row["contract_id"]),
            "previous_status": previous_status,
            "status": "deleting",
        }

    def restore_instance_status(self, instance_id: str, status: str) -> None:
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            session.execute(
                f"UPDATE instances SET status={ph} WHERE id={ph} AND status={ph}",
                (status or "offline", instance_id, "deleting"),
            )

    def begin_contract_delete(self, contract_id: str) -> dict[str, Any]:
        """Mark a contract and every bound instance for cascading removal."""
        contract_id = self._identifier(contract_id, "contract_id")
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            contract = session.execute(
                "SELECT id,customer_id,game_id,status FROM service_contracts "
                f"WHERE id={ph}",
                (contract_id,),
            ).fetchone()
            if contract is None:
                raise ValueError("contract not found")
            rows = session.execute(
                "SELECT i.id AS instance_id,i.agent_id,i.status AS instance_status,a.status AS agent_status "
                "FROM instance_contracts ic JOIN instances i ON i.id=ic.instance_id "
                "LEFT JOIN agents a ON a.id=i.agent_id "
                f"WHERE ic.contract_id={ph} ORDER BY i.id",
                (contract_id,),
            ).fetchall()
            blocked = [
                str(row["instance_id"]) for row in rows
                if str(row["agent_status"] or "").lower() != "active"
            ]
            if blocked:
                raise RuntimeError(
                    "cannot delete contract while owning Agents are inactive: "
                    + ", ".join(blocked)
                )
            if not rows:
                session.execute(
                    f"DELETE FROM service_contracts WHERE id={ph}", (contract_id,)
                )
                return {
                    "contract_id": contract_id,
                    "customer_id": str(contract["customer_id"]),
                    "game_id": str(contract["game_id"]),
                    "status": "deleted",
                    "instances": [],
                }
            session.execute(
                f"UPDATE service_contracts SET status={ph} WHERE id={ph}",
                ("deleting", contract_id),
            )
            for row in rows:
                session.execute(
                    f"UPDATE instances SET status={ph} WHERE id={ph}",
                    ("deleting", row["instance_id"]),
                )
        return {
            "contract_id": contract_id,
            "customer_id": str(contract["customer_id"]),
            "game_id": str(contract["game_id"]),
            "status": "deleting",
            "instances": [
                {
                    "instance_id": str(row["instance_id"]),
                    "agent_id": str(row["agent_id"]),
                    "previous_status": str(row["instance_status"] or "offline"),
                }
                for row in rows
            ],
        }

    def finalize_contract_if_empty(self, contract_id: str | None) -> bool:
        if not contract_id:
            return False
        contract_id = self._identifier(contract_id, "contract_id")
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            contract = session.execute(
                f"SELECT status FROM service_contracts WHERE id={ph}",
                (contract_id,),
            ).fetchone()
            if contract is None or str(contract["status"] or "").lower() != "deleting":
                return False
            count = session.execute(
                f"SELECT COUNT(*) AS total FROM instance_contracts WHERE contract_id={ph}",
                (contract_id,),
            ).fetchone()
            if int(count["total"] or 0) != 0:
                return False
            session.execute(
                f"DELETE FROM service_contracts WHERE id={ph}", (contract_id,)
            )
        return True


__all__ = ["AdminManagementRepository"]
