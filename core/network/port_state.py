"""Normalized state model for instance network endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PortState:
    name: str
    protocol: str
    port: int
    bind_address: str
    state: str
    purpose: str | None = None
    public: bool = False
    externally_reachable: bool | None = None
    detail: str | None = None


def build_port_states(
    reservations: Iterable[Mapping[str, Any]],
    *,
    listening: Mapping[str, set[int]] | None = None,
    public_names: set[str] | None = None,
    purposes: Mapping[str, str] | None = None,
) -> list[PortState]:
    listening = listening or {}
    public_names = public_names or set()
    purposes = purposes or {}

    result: list[PortState] = []

    for reservation in reservations:
        name = str(reservation["name"])
        protocol = str(reservation["protocol"]).lower()
        port = int(reservation["port"])
        bind_address = str(
            reservation.get("bind_address") or "0.0.0.0"
        )

        active = port in listening.get(protocol, set())

        result.append(
            PortState(
                name=name,
                protocol=protocol,
                port=port,
                bind_address=bind_address,
                state=("listening" if active else "reserved"),
                purpose=purposes.get(name),
                public=name in public_names,
            )
        )

    return result
