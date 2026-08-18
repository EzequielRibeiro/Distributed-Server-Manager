
"""Generic network allocation subsystem for Capivara DSM."""

from .port_allocator import (
    PortAllocation,
    PortAllocationError,
    PortRange,
    allocate_port_profile,
)
from .port_profile import (
    NetworkApplication,
    PortProfile,
    PortRequirement,
)

__all__ = [
    "NetworkApplication",
    "PortAllocation",
    "PortAllocationError",
    "PortProfile",
    "PortRange",
    "PortRequirement",
    "allocate_port_profile",
]
