#!/usr/bin/env python3
"""Transactional reconciliation for legacy instance port reservations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from core.network.port_allocator import PortRange
from core.network.port_profile import PortProfile


class InstancePortReconcileError(RuntimeError):
    """The persisted reservation set cannot be reconciled safely."""


@dataclass(frozen=True)
class ReconcilePlan:
    base_port: int
    ports: dict[str, int]
    missing: tuple[str, ...]


def _inside_active_range(protocol: str, port: int, ranges: Iterable[PortRange]) -> bool:
    return any(
        item.protocol == protocol and item.start_port <= port <= item.end_port
        for item in ranges
    )


def plan_instance_port_reconcile(
    profile: PortProfile,
    existing_rows: Iterable[Mapping[str, Any]],
    ranges: Iterable[PortRange],
    *,
    conflicts: Mapping[str, set[int]] | None = None,
    occupied: Mapping[str, set[int]] | None = None,
) -> ReconcilePlan:
    """Plan missing reservations without moving any already-persisted port."""
    rows = [dict(row) for row in existing_rows]
    ranges = tuple(ranges)
    conflicts = conflicts or {}
    occupied = occupied or {}
    requirements = {item.name: item for item in profile.ports}

    if not rows:
        raise InstancePortReconcileError("instance has no persisted network reservation anchor")

    unexpected = sorted({str(row.get("name") or "") for row in rows} - set(requirements))
    if unexpected:
        raise InstancePortReconcileError(
            "instance has reservations outside the current runtime profile: "
            + ", ".join(unexpected)
        )

    bases: set[int] = set()
    seen_names: set[str] = set()
    normalized: dict[str, tuple[str, int, str]] = {}

    for row in rows:
        name = str(row.get("name") or "").strip().lower()
        requirement = requirements[name]
        if name in seen_names:
            raise InstancePortReconcileError(f"duplicate persisted reservation role: {name}")
        seen_names.add(name)
        protocol = str(row.get("protocol") or "").strip().lower()
        port = int(row.get("port"))
        bind_address = str(row.get("bind_address") or requirement.bind_address).strip()
        if protocol != requirement.protocol:
            raise InstancePortReconcileError(
                f"persisted reservation protocol mismatch for {name}"
            )
        bases.add(port - requirement.offset)
        normalized[name] = (protocol, port, bind_address)

    if len(bases) != 1:
        raise InstancePortReconcileError("persisted reservations do not share one logical port block")

    base_port = bases.pop()
    if not 1 <= base_port <= 65535:
        raise InstancePortReconcileError("derived network port block base is invalid")

    expected: dict[str, int] = {}
    missing: list[str] = []
    for requirement in profile.ports:
        port = base_port + requirement.offset
        if not 1 <= port <= 65535:
            raise InstancePortReconcileError(
                f"derived reservation is outside valid port range for {requirement.name}"
            )
        if not _inside_active_range(requirement.protocol, port, ranges):
            raise InstancePortReconcileError(
                f"derived reservation is outside active Agent ranges for {requirement.name}"
            )
        expected[requirement.name] = port
        persisted = normalized.get(requirement.name)
        if persisted is not None:
            if persisted[1] != port:
                raise InstancePortReconcileError(
                    f"persisted reservation does not match logical block for {requirement.name}"
                )
            continue
        if port in conflicts.get(requirement.protocol, set()):
            raise InstancePortReconcileError(
                f"derived reservation collides with another instance for {requirement.name}"
            )
        if port in occupied.get(requirement.protocol, set()):
            raise InstancePortReconcileError(
                f"derived reservation is occupied by an unmanaged socket for {requirement.name}"
            )
        missing.append(requirement.name)

    return ReconcilePlan(base_port=base_port, ports=expected, missing=tuple(missing))


def reconcile_instance_ports(
    repository,
    instance_id: str,
    network_profile: Mapping[str, Any],
    *,
    occupied_ports_provider,
) -> dict[str, Any]:
    """Backfill missing current-profile reservations atomically and idempotently."""
    repository.initialize()
    profile = PortProfile.from_reservations(network_profile)
    if profile is None:
        raise InstancePortReconcileError("runtime network profile is unavailable")
    if occupied_ports_provider is None:
        raise InstancePortReconcileError("operating-system port inspection provider is required")

    ph = repository.dialect.placeholder
    with repository.session(transaction=True) as session:
        lock = " FOR UPDATE" if repository.backend.name in {"postgresql", "mysql"} else ""
        instance = session.execute(
            "SELECT id,node_id,agent_id,metadata_json FROM instances "
            f"WHERE id={ph}{lock}",
            (str(instance_id),),
        ).fetchone()
        if instance is None:
            raise InstancePortReconcileError("instance is unavailable")
        if not instance["agent_id"] or not instance["node_id"]:
            raise InstancePortReconcileError("instance is not bound to an Agent and node")

        if repository.backend.name in {"postgresql", "mysql"}:
            agent = session.execute(
                "SELECT id FROM agents " f"WHERE id={ph} FOR UPDATE",
                (instance["agent_id"],),
            ).fetchone()
            if agent is None:
                raise InstancePortReconcileError("bound Agent is unavailable")

        range_rows = session.execute(
            "SELECT protocol,start_port,end_port FROM agent_port_ranges "
            f"WHERE agent_id={ph} AND status='active' ORDER BY protocol,start_port",
            (instance["agent_id"],),
        ).fetchall()
        ranges = tuple(
            PortRange(
                protocol=row["protocol"],
                start_port=int(row["start_port"]),
                end_port=int(row["end_port"]),
            )
            for row in range_rows
        )
        if not ranges:
            raise InstancePortReconcileError("bound Agent has no active port range")

        existing_rows = session.execute(
            "SELECT name,protocol,port,bind_address FROM instance_ports "
            f"WHERE instance_id={ph} ORDER BY name",
            (str(instance_id),),
        ).fetchall()

        other_rows = session.execute(
            "SELECT protocol,port FROM instance_ports "
            f"WHERE node_id={ph} AND instance_id<>{ph}",
            (instance["node_id"], str(instance_id)),
        ).fetchall()
        conflicts: dict[str, set[int]] = {"tcp": set(), "udp": set()}
        for row in other_rows:
            protocol = str(row["protocol"]).lower()
            if protocol in conflicts:
                conflicts[protocol].add(int(row["port"]))

        # Derive the legacy block first without OS occupancy so we know exactly
        # which missing ports need inspection. Existing ports may legitimately
        # be listening for this instance and must not be treated as conflicts.
        preliminary = plan_instance_port_reconcile(
            profile,
            existing_rows,
            ranges,
            conflicts=conflicts,
        )
        requirements = {item.name: item for item in profile.ports}
        occupied: dict[str, set[int]] = {"tcp": set(), "udp": set()}
        for name in preliminary.missing:
            requirement = requirements[name]
            port = preliminary.ports[name]
            observed = occupied_ports_provider(
                instance["agent_id"],
                instance["node_id"],
                requirement.protocol,
                port,
                port,
            )
            occupied[requirement.protocol].update(int(value) for value in observed or set())

        plan = plan_instance_port_reconcile(
            profile,
            existing_rows,
            ranges,
            conflicts=conflicts,
            occupied=occupied,
        )

        for name in plan.missing:
            requirement = requirements[name]
            session.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port,bind_address) "
                f"VALUES ({repository.dialect.parameters(6)})",
                (
                    str(instance_id),
                    instance["node_id"],
                    name,
                    requirement.protocol,
                    plan.ports[name],
                    requirement.bind_address,
                ),
            )

        try:
            metadata = json.loads(instance["metadata_json"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        network = metadata.get("network") if isinstance(metadata.get("network"), dict) else {}
        network = dict(network)
        network["ports"] = dict(plan.ports)
        metadata["network"] = network
        session.execute(
            "UPDATE instances " f"SET metadata_json={ph} WHERE id={ph}",
            (json.dumps(metadata, ensure_ascii=False), str(instance_id)),
        )

    return {
        "instance_id": str(instance_id),
        "base_port": plan.base_port,
        "ports": dict(plan.ports),
        "inserted": list(plan.missing),
        "changed": bool(plan.missing),
    }


__all__ = [
    "InstancePortReconcileError",
    "ReconcilePlan",
    "plan_instance_port_reconcile",
    "reconcile_instance_ports",
]
