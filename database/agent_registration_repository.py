#!/usr/bin/env python3
"""Persistence for discovering/registering Agents before pairing."""

from __future__ import annotations

from dataclasses import dataclass

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class ControllerNotFound(LookupError):
    pass


class ControllerInactive(ValueError):
    pass


class AgentRegistrationConflict(ValueError):
    pass


@dataclass(frozen=True)
class RegisteredAgent:
    agent_id: str
    controller_id: str
    node_id: str
    name: str
    status: str


class AgentRegistrationRepository:
    """Create Agent identities transactionally before trust is established."""

    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def _create(
        self,
        *,
        controller_id: str,
        agent_id: str,
        node_id: str,
        name: str,
        status: str,
        metadata_json: str = "{}",
    ) -> RegisteredAgent:
        controller_id = str(controller_id).strip()
        agent_id = str(agent_id).strip()
        node_id = str(node_id).strip()
        name = str(name).strip()
        if not all((controller_id, agent_id, node_id, name)):
            raise ValueError("controller_id, agent_id, node_id and name are required")
        if status not in {"discovered", "pending"}:
            raise ValueError("registration status must be discovered or pending")

        ph = self.dialect.placeholder
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                controller = session.execute(
                    f"SELECT status FROM controllers WHERE id={ph}", (controller_id,)
                ).fetchone()
                if controller is None:
                    raise ControllerNotFound(f"Controller not found: {controller_id}")
                if str(controller["status"]).strip().lower() != "active":
                    raise ControllerInactive(f"Controller is not active: {controller_id}")
                if session.execute(
                    f"SELECT 1 FROM agents WHERE id={ph}", (agent_id,)
                ).fetchone() is not None:
                    raise AgentRegistrationConflict(f"Agent already exists: {agent_id}")
                if session.execute(
                    f"SELECT 1 FROM nodes WHERE id={ph}", (node_id,)
                ).fetchone() is not None:
                    raise AgentRegistrationConflict(f"Node already exists: {node_id}")

                session.execute(
                    "INSERT INTO nodes(id,name,role,status,metadata_json) "
                    f"VALUES ({self.dialect.parameters(5)})",
                    (node_id, name, "agent", status, metadata_json),
                )
                session.execute(
                    "INSERT INTO agents(id,controller_id,node_id,name,status,metadata_json) "
                    f"VALUES ({self.dialect.parameters(6)})",
                    (agent_id, controller_id, node_id, name, status, metadata_json),
                )
            finally:
                session.close()

        return RegisteredAgent(agent_id, controller_id, node_id, name, status)

    def discover(self, **kwargs) -> RegisteredAgent:
        """Persist an untrusted Agent observed by a Controller."""
        return self._create(status="discovered", **kwargs)

    def register(self, **kwargs) -> RegisteredAgent:
        """Preserve the Phase 2 contract: explicit registration starts pending."""
        return self._create(status="pending", **kwargs)
