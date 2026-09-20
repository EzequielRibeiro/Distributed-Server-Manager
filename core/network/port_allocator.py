
"""Backend-independent generic port block allocator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .port_profile import PortProfile


class PortAllocationError(RuntimeError):
    """No valid block can satisfy a network profile."""


@dataclass(frozen=True)
class PortRange:
    protocol: str
    start_port: int
    end_port: int

    def __post_init__(self):
        protocol = self.protocol.lower()

        if protocol not in {
            "tcp",
            "udp",
        }:
            raise ValueError(
                f"invalid protocol: {self.protocol}"
            )

        if not (
            1
            <= int(self.start_port)
            <= int(self.end_port)
            <= 65535
        ):
            raise ValueError(
                "invalid port range"
            )

        object.__setattr__(
            self,
            "protocol",
            protocol,
        )


@dataclass(frozen=True)
class PortAllocation:
    base_port: int
    ports: dict[str, int]


def _inside_any_range(
    protocol: str,
    port: int,
    ranges: Iterable[PortRange],
) -> bool:
    return any(
        item.protocol == protocol
        and item.start_port <= port <= item.end_port
        for item in ranges
    )


def allocate_port_profile(
    profile: PortProfile,
    ranges: Iterable[PortRange],
    *,
    reserved: Mapping[
        str,
        set[int],
    ] | None = None,
    occupied: Mapping[
        str,
        set[int],
    ] | None = None,
) -> PortAllocation:
    """
    Select a valid logical block.

    This function has no database or operating-system dependency.
    """

    ranges = tuple(ranges)

    if not ranges:
        raise PortAllocationError(
            "agent has no active port range"
        )

    reserved = reserved or {}
    occupied = occupied or {}

    # Numeric ports are owned per node, not per protocol. A reservation or
    # unmanaged listener on 24000/UDP therefore also blocks 24000/TCP for a
    # different instance. Runtime profiles may still intentionally bind the
    # same numeric port on TCP and UDP inside one allocation (for example
    # Source-style servers), because these sets contain only external usage.
    reserved_numbers = {
        int(port)
        for ports in reserved.values()
        for port in ports
    }
    occupied_numbers = {
        int(port)
        for ports in occupied.values()
        for port in ports
    }

    anchor = next(
        (
            port
            for port in profile.ports
            if port.offset == 0
        ),
        None,
    )

    if anchor is None:
        raise PortAllocationError(
            "network profile has no anchor port"
        )

    anchor_ranges = [
        item
        for item in ranges
        if item.protocol == anchor.protocol
    ]

    if not anchor_ranges:
        raise PortAllocationError(
            f"agent has no {anchor.protocol} port range"
        )

    for anchor_range in anchor_ranges:
        candidate = anchor_range.start_port

        while candidate <= anchor_range.end_port:
            calculated: dict[str, int] = {}
            valid = True

            for requirement in profile.ports:
                port = (
                    candidate
                    + requirement.offset
                )

                if port > 65535:
                    valid = False
                    break

                if not _inside_any_range(
                    requirement.protocol,
                    port,
                    ranges,
                ):
                    valid = False
                    break

                if port in reserved_numbers:
                    valid = False
                    break

                if port in occupied_numbers:
                    valid = False
                    break

                calculated[
                    requirement.name
                ] = port

            if valid:
                return PortAllocation(
                    base_port=candidate,
                    ports=calculated,
                )

            candidate += profile.block_size

    raise PortAllocationError(
        "no network port block is available "
        "for the requested runtime profile"
    )
