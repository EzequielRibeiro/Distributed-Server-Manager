#!/usr/bin/env python3
"""Backend-independent instance ownership registry persistence."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend


class InfrastructureIdentityConflict(ValueError):
    """Raised when an installation identity conflicts with persisted data."""


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

    def _row(
        self,
        session: AlertSession,
        sql: str,
        parameters: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        row = session.execute(sql, parameters).fetchone()
        return None if row is None else dict(row)

    def _ensure_node(
        self,
        session: AlertSession,
        *,
        node_id: str,
        name: str,
        role: str,
        initial_status: str,
        allowed_existing_roles: set[str],
    ) -> dict[str, Any]:
        ph = self.dialect.placeholder
        existing = self._row(
            session,
            f"SELECT id,name,role,status FROM nodes WHERE id={ph}",
            (node_id,),
        )
        if existing is None:
            session.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES "
                f"({self.dialect.parameters(4)})",
                (node_id, name, role, initial_status),
            )
            return {
                "id": node_id,
                "name": name,
                "role": role,
                "status": initial_status,
            }

        existing_role = str(existing["role"]).strip().lower()
        if existing_role not in allowed_existing_roles:
            raise InfrastructureIdentityConflict(
                f"Node {node_id} already belongs to role {existing_role}"
            )
        return existing

    def bootstrap_installation_profile(
        self,
        *,
        profile: str,
        node_id: str,
        node_name: str,
        controller_id: str | None = None,
        controller_name: str | None = None,
        agent_id: str | None = None,
        agent_name: str | None = None,
        region_id: str | None = None,
        region_name: str | None = None,
        datacenter_id: str | None = None,
        datacenter_name: str | None = None,
    ) -> dict[str, Any]:
        """Bootstrap infrastructure identity for an installation profile.

        Controller installations create only their local Controller identity.
        Standalone Agent installations create a local pending Agent node but do
        not fabricate a Controller-owned ``agents`` row; that row is created by
        the real enrollment flow on a Controller. Hybrid installations create a
        trusted local Controller + Agent on one hybrid node and a minimal local
        geographic topology so the Agent is immediately placement-eligible.

        Existing matching records are preserved instead of force-reactivated.
        This makes reinstall safe for disabled/offline identities.
        """
        profile = str(profile).strip().lower()
        node_id = str(node_id).strip()
        node_name = str(node_name).strip()

        if profile not in {"controller", "agent", "hybrid"}:
            raise ValueError(f"invalid installation profile: {profile}")
        if not node_id:
            raise ValueError("node_id is required")
        if not node_name:
            raise ValueError("node_name is required")

        self.initialize()
        ph = self.dialect.placeholder

        with self.transaction() as session:
            if profile == "controller":
                controller_id = str(controller_id or "").strip()
                controller_name = str(controller_name or node_name).strip()
                if not controller_id:
                    raise ValueError("controller_id is required")

                node = self._ensure_node(
                    session,
                    node_id=node_id,
                    name=node_name,
                    role="controller",
                    initial_status="active",
                    allowed_existing_roles={"controller", "hybrid"},
                )
                controller = self._row(
                    session,
                    f"SELECT id,node_id,name,status FROM controllers WHERE id={ph}",
                    (controller_id,),
                )
                if controller is None:
                    session.execute(
                        "INSERT INTO controllers(id,node_id,name,status) VALUES "
                        f"({self.dialect.parameters(4)})",
                        (controller_id, node_id, controller_name, "active"),
                    )
                    controller_status = "active"
                else:
                    if str(controller["node_id"]) != node_id:
                        raise InfrastructureIdentityConflict(
                            f"Controller {controller_id} already belongs to "
                            f"node {controller['node_id']}"
                        )
                    controller_status = str(controller["status"])

                return {
                    "profile": profile,
                    "node_id": node_id,
                    "node_role": str(node["role"]),
                    "node_status": str(node["status"]),
                    "controller_id": controller_id,
                    "controller_status": controller_status,
                    "agent_id": None,
                    "agent_status": None,
                    "topology_state": "unconfigured",
                    "placement_ready": False,
                }

            if profile == "agent":
                agent_id = str(agent_id or "").strip()
                agent_name = str(agent_name or node_name).strip()
                if not agent_id:
                    raise ValueError("agent_id is required")

                node = self._ensure_node(
                    session,
                    node_id=node_id,
                    name=agent_name,
                    role="agent",
                    initial_status="pending",
                    allowed_existing_roles={"agent", "hybrid"},
                )

                by_id = self._row(
                    session,
                    f"SELECT id,controller_id,node_id,name,status "
                    f"FROM agents WHERE id={ph}",
                    (agent_id,),
                )
                by_node = self._row(
                    session,
                    f"SELECT id,controller_id,node_id,name,status "
                    f"FROM agents WHERE node_id={ph}",
                    (node_id,),
                )

                if by_id is not None and str(by_id["node_id"]) != node_id:
                    raise InfrastructureIdentityConflict(
                        f"Agent {agent_id} already belongs to node {by_id['node_id']}"
                    )
                if by_node is not None and str(by_node["id"]) != agent_id:
                    raise InfrastructureIdentityConflict(
                        f"Node {node_id} already belongs to Agent {by_node['id']}"
                    )

                registered = by_id or by_node
                return {
                    "profile": profile,
                    "node_id": node_id,
                    "node_role": str(node["role"]),
                    "node_status": str(node["status"]),
                    "controller_id": (
                        None if registered is None else registered["controller_id"]
                    ),
                    "agent_id": agent_id,
                    "agent_status": (
                        str(node["status"])
                        if registered is None
                        else str(registered["status"])
                    ),
                    "registered_with_controller": registered is not None,
                    "awaiting_pairing": registered is None,
                    "topology_state": "unconfigured",
                    "placement_ready": False,
                }

            controller_id = str(controller_id or "").strip()
            controller_name = str(controller_name or node_name).strip()
            agent_id = str(agent_id or "").strip()
            agent_name = str(agent_name or node_name).strip()
            region_id = str(region_id or "").strip()
            region_name = str(region_name or "Local").strip()
            datacenter_id = str(datacenter_id or "").strip()
            datacenter_name = str(datacenter_name or "Local").strip()

            for identifier, label in (
                (controller_id, "controller_id"),
                (agent_id, "agent_id"),
                (region_id, "region_id"),
                (datacenter_id, "datacenter_id"),
            ):
                if not identifier:
                    raise ValueError(f"{label} is required")

            node = self._ensure_node(
                session,
                node_id=node_id,
                name=node_name,
                role="hybrid",
                initial_status="active",
                allowed_existing_roles={"hybrid"},
            )

            controller = self._row(
                session,
                f"SELECT id,node_id,name,status FROM controllers WHERE id={ph}",
                (controller_id,),
            )
            if controller is None:
                session.execute(
                    "INSERT INTO controllers(id,node_id,name,status) VALUES "
                    f"({self.dialect.parameters(4)})",
                    (controller_id, node_id, controller_name, "active"),
                )
                controller_status = "active"
            else:
                if str(controller["node_id"]) != node_id:
                    raise InfrastructureIdentityConflict(
                        f"Controller {controller_id} already belongs to "
                        f"node {controller['node_id']}"
                    )
                controller_status = str(controller["status"])

            agent = self._row(
                session,
                f"SELECT id,controller_id,node_id,name,status "
                f"FROM agents WHERE id={ph}",
                (agent_id,),
            )
            if agent is None:
                session.execute(
                    "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES "
                    f"({self.dialect.parameters(5)})",
                    (agent_id, controller_id, node_id, agent_name, "active"),
                )
                agent_status = "active"
            else:
                if (
                    str(agent["controller_id"]) != controller_id
                    or str(agent["node_id"]) != node_id
                ):
                    raise InfrastructureIdentityConflict(
                        f"Agent {agent_id} conflicts with the local hybrid identity"
                    )
                agent_status = str(agent["status"])

            region = self._row(
                session,
                f"SELECT id,status FROM regions WHERE id={ph}",
                (region_id,),
            )
            if region is None:
                session.execute(
                    "INSERT INTO regions(id,name,status) VALUES "
                    f"({self.dialect.parameters(3)})",
                    (region_id, region_name, "active"),
                )
                region_status = "active"
            else:
                region_status = str(region["status"])

            datacenter = self._row(
                session,
                f"SELECT id,region_id,status FROM datacenters WHERE id={ph}",
                (datacenter_id,),
            )
            if datacenter is None:
                session.execute(
                    "INSERT INTO datacenters(id,region_id,name,status) VALUES "
                    f"({self.dialect.parameters(4)})",
                    (datacenter_id, region_id, datacenter_name, "active"),
                )
                datacenter_status = "active"
            else:
                if str(datacenter["region_id"]) != region_id:
                    raise InfrastructureIdentityConflict(
                        f"Datacenter {datacenter_id} belongs to another Region"
                    )
                datacenter_status = str(datacenter["status"])

            location = self._row(
                session,
                f"SELECT agent_id,datacenter_id,status "
                f"FROM agent_locations WHERE agent_id={ph}",
                (agent_id,),
            )
            if location is None:
                session.execute(
                    "INSERT INTO agent_locations(agent_id,datacenter_id,status) VALUES "
                    f"({self.dialect.parameters(3)})",
                    (agent_id, datacenter_id, "active"),
                )
                location_status = "active"
            else:
                if str(location["datacenter_id"]) != datacenter_id:
                    raise InfrastructureIdentityConflict(
                        f"Agent {agent_id} already belongs to another Datacenter"
                    )
                location_status = str(location["status"])

            topology_ready = all(
                status.strip().lower() == "active"
                for status in (
                    region_status,
                    datacenter_status,
                    location_status,
                )
            )
            placement_ready = (
                controller_status.strip().lower() == "active"
                and agent_status.strip().lower() == "active"
                and topology_ready
            )

            return {
                "profile": profile,
                "node_id": node_id,
                "node_role": str(node["role"]),
                "node_status": str(node["status"]),
                "controller_id": controller_id,
                "controller_status": controller_status,
                "agent_id": agent_id,
                "agent_status": agent_status,
                "region_id": region_id,
                "datacenter_id": datacenter_id,
                "topology_state": "ready" if topology_ready else "partial",
                "placement_ready": placement_ready,
            }

    def bootstrap_topology(
        self,
        *,
        controller_id: str,
        controller_node_id: str,
        controller_name: str,
        agent_id: str,
        agent_node_id: str,
        agent_name: str,
    ) -> dict[str, Any]:
        """Create or reconcile the first production controller and agent."""
        self.initialize()
        with self.transaction() as session:
            self._upsert(session, "nodes", "id", {
                "id": controller_node_id,
                "name": controller_name,
                "role": "controller",
                "status": "active",
            })
            self._upsert(session, "controllers", "id", {
                "id": controller_id,
                "node_id": controller_node_id,
                "name": controller_name,
                "status": "active",
            })
            self._upsert(session, "nodes", "id", {
                "id": agent_node_id,
                "name": agent_name,
                "role": "agent",
                "status": "active",
            })
            self._upsert(session, "agents", "id", {
                "id": agent_id,
                "controller_id": controller_id,
                "node_id": agent_node_id,
                "name": agent_name,
                "status": "active",
            })
        return {
            "controller_id": controller_id,
            "controller_node_id": controller_node_id,
            "agent_id": agent_id,
            "agent_node_id": agent_node_id,
        }

    def topology_status(self) -> dict[str, Any]:
        """Return first-class, explainable placement readiness."""
        from placement_status_repository import PlacementStatusRepository

        return PlacementStatusRepository(self.backend).snapshot()

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
