#!/usr/bin/env python3
"""Effective Agent port availability from DSM reservations plus observed sockets."""

from __future__ import annotations

from typing import Any

from agent_port_repository import AgentPortRepository
from agent_runtime_repository import AgentRuntimeRepository, AgentRuntimeNotFound


def _observed_ports(network: dict[str, Any], protocol: str) -> set[int]:
    key = "tcp_listen" if protocol == "tcp" else "udp_listen"
    values = network.get(key, []) if isinstance(network, dict) else []
    ports: set[int] = set()
    for value in values if isinstance(values, list) else []:
        try:
            port = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return ports


def _largest_contiguous(start: int, end: int, occupied: set[int]) -> int:
    largest = 0
    current = 0
    for port in range(start, end + 1):
        if port in occupied:
            current = 0
            continue
        current += 1
        largest = max(largest, current)
    return largest


def effective_port_summary(
    backend,
    agent_id: str,
    *,
    initialize: bool = True,
    refresh_runtime_health: bool = True,
) -> dict[str, Any]:
    """Return configured ranges enriched with observed host usage.

    Defaults preserve operational behavior. Diagnostic callers may disable
    initialization and runtime-health refresh to keep the entire read path
    strictly observational.
    """
    repository = AgentPortRepository(backend)
    if initialize:
        repository.initialize()
    base = repository.summary(agent_id)

    try:
        runtime = AgentRuntimeRepository(backend).snapshot(
            agent_id,
            refresh_health=refresh_runtime_health,
        )
    except AgentRuntimeNotFound:
        runtime = {}
    # ``agents.status`` is the administrative lifecycle (for example active),
    # not connectivity.  Expose the derived heartbeat projection separately so
    # the Dashboard never mistakes an enabled but powered-off Agent for online.
    base_agent = dict(base.get("agent") or {})
    for field in (
        "hostname", "os_name", "architecture", "capivara_version", "address",
        "health_status", "last_seen",
    ):
        if field in runtime:
            base_agent[field] = runtime.get(field)
    base["agent"] = base_agent
    network = runtime.get("network") if isinstance(runtime.get("network"), dict) else {}

    reservations = base.get("reservations", [])
    observed_conflicts: list[dict[str, Any]] = []
    enriched_ranges: list[dict[str, Any]] = []

    for item in base.get("ranges", []):
        protocol = str(item["protocol"]).lower()
        start = int(item["start_port"])
        end = int(item["end_port"])
        reserved_ports = {
            int(row["port"])
            for row in reservations
            if str(row.get("protocol", "")).lower() == protocol
            and start <= int(row["port"]) <= end
        }
        observed = {
            port for port in _observed_ports(network, protocol)
            if start <= port <= end
        }
        unmanaged = observed - reserved_ports
        for port in sorted(unmanaged):
            observed_conflicts.append(
                {"protocol": protocol, "port": port, "source": "os_socket"}
            )
        occupied = reserved_ports | observed
        capacity = end - start + 1
        available = max(capacity - len(occupied), 0)
        enriched_ranges.append(
            {
                **item,
                "capacity": capacity,
                "reserved": len(reserved_ports),
                "observed_occupied": len(observed),
                "effective_occupied": len(occupied),
                "available": available,
                "largest_contiguous_available": _largest_contiguous(start, end, occupied),
                "usage_pct": round((100.0 * len(occupied) / capacity) if capacity else 100.0, 2),
                "near_exhaustion": available <= max(5, int(capacity * 0.10)),
            }
        )

    persistent_conflicts = list(base.get("conflicts", []))
    conflicts = persistent_conflicts + observed_conflicts
    return {
        **base,
        "ranges": enriched_ranges,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "persistent_conflict_count": len(persistent_conflicts),
        "observed_conflict_count": len(observed_conflicts),
    }


__all__ = ["effective_port_summary"]
