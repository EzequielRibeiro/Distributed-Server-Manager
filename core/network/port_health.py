"""Health inspection for ports reserved by Capivara DSM."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping

from .port_inspector import LocalPortInspector
from .port_state import build_port_states


def inspect_reserved_ports(
    reservations: Iterable[Mapping[str, Any]],
    *,
    inspector=None,
    public_names: set[str] | None = None,
    purposes: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    reservations = [dict(item) for item in reservations]

    inspector = inspector or LocalPortInspector()

    listening: dict[str, set[int]] = {
        "tcp": set(),
        "udp": set(),
    }

    for protocol in ("tcp", "udp"):
        ports = [
            int(item["port"])
            for item in reservations
            if str(item["protocol"]).lower() == protocol
        ]

        if not ports:
            continue

        start_port = min(ports)
        end_port = max(ports)

        listening[protocol] = inspector.occupied(
            protocol,
            start_port,
            end_port,
        )

    states = build_port_states(
        reservations,
        listening=listening,
        public_names=public_names,
        purposes=purposes,
    )

    return [asdict(item) for item in states]
