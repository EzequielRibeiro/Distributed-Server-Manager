"""Optional Catalog network roles are allocated only on explicit opt-in."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.network.port_profile import PortProfile


def enabled_network_profile(
    runtime: Mapping[str, Any],
    *,
    optional_roles: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Prepare an immutable runtime-derived allocation profile.

    A selected on-demand role is validated by PortProfile alongside the
    required roles. Unselected roles are not reserved and cannot consume
    another instance's numeric port.
    """
    network = deepcopy(runtime.get("network") or {})
    available = network.get("on_demand_ports") or []
    if not isinstance(available, list):
        raise ValueError("Catalog on-demand port definitions must be an array")
    available_by_name = {
        str(item.get("name") or ""): item
        for item in available if isinstance(item, dict)
    }
    if len(available_by_name) != len(available):
        raise ValueError("Catalog has duplicate or invalid optional port roles")
    if not optional_roles.issubset(available_by_name):
        raise ValueError("requested optional service is unsupported by this runtime")
    if set(available_by_name).intersection(
        str(item.get("name") or "") for item in network.get("ports") or []
    ):
        raise ValueError("optional service overlaps a mandatory port role")
    for role in sorted(optional_roles):
        item = available_by_name[role]
        network["ports"].append(deepcopy(item))
        network.setdefault("apply", []).append({"kind": "reserve", "port": role})
    # This is the effective allocation contract, not a catalog definition.
    # Legacy roles are only for persisted pre-change instance reservations.
    network.pop("legacy_reservations", None)
    network.pop("on_demand_ports", None)
    PortProfile.from_mapping(network)
    return network
