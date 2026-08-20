#!/usr/bin/env python3
"""Persistence for registering new Agents before pairing.

Registration creates the backing node and Agent atomically in ``pending``
state. Activation is intentionally left to the lifecycle/pairing flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class ControllerNotFound(LookupError):
    """Raised when the requested Controller does not exist."""


class ControllerInactive(ValueError):
    """Raised when registration targets a non-active Controller."""


class AgentRegistrationConflict(ValueError):
    """Raised when Agent or node identity is already registered."""


@dataclass(frozen=True)
class RegisteredAgent:
    agent_id: str
    controller_id: str
    node_id: str
    name: str
    status: str = "pending"


class AgentRegistrationRepository:
    """Create pending Agent identities transactionally."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def register(
        self,
        *,
        controller_id: str,
        agent_id: str,
        node_id: str,
        name: str,
        metadata_json: str = "{}",
    ) -> RegisteredAgent:
        controller_id = str(controller_id).strip()
        agent_id = str(agent_id).strip()
        node_id = str(node_id).strip()
        name = str(name).strip()

        if not controller_id:
            raise ValueError("controller_id is required")
        if not agent_id:
            raise ValueError("agent_id is required")
        if not node_id:
            raise ValueError("node_id is required")
        if not name:
            raise ValueError("name is required")

        ph = self.dialect.placeholder

        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                controller = session.execute(
                    f"SELECT status FROM controllers WHERE id={ph}",
                    (controller_id,),
                ).fetchone()
                if controller is None:
                    raise ControllerNotFound(
                        f"Controller not found: {controller_id}"
                    )
                if str(controller["status"]).strip().lower() != "active":
                    raise ControllerInactive(
                        f"Controller is not active: {controller_id}"
                    )

                if session.execute(
                    f"SELECT 1 FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone() is not None:
                    raise AgentRegistrationConflict(
                        f"Agent already exists: {agent_id}"
                    )

                if session.execute(
                    f"SELECT 1 FROM nodes WHERE id={ph}",
                    (node_id,),
                ).fetchone() is not None:
                    raise AgentRegistrationConflict(
                        f"Node already exists: {node_id}"
                    )

                session.execute(
                    "INSERT INTO nodes(id,name,role,status,metadata_json) "
                    f"VALUES ({self.dialect.parameters(5)})",
                    (node_id, name, "agent", "pending", metadata_json),
                )
                session.execute(
                    "INSERT INTO agents("
                    "id,controller_id,node_id,name,status,metadata_json"
                    ") VALUES "
                    f"({self.dialect.parameters(6)})",
                    (
                        agent_id,
                        controller_id,
                        node_id,
                        name,
                        "pending",
                        metadata_json,
                    ),
                )
            finally:
                session.close()

        return RegisteredAgent(
            agent_id=agent_id,
            controller_id=controller_id,
            node_id=node_id,
            name=name,
        )
