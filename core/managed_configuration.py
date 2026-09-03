"""Generic Managed Configuration boundary for Capivara DSM P1."""
from __future__ import annotations
from typing import Any, Mapping
from core.configuration_precedence import resolve_configuration_precedence

MANAGED_CONFIGURATION_VERSION = 1


def resolve_managed_configuration(*, system: Mapping[str, Any] | None = None, contract: Mapping[str, Any] | None = None, customer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    resolved = resolve_configuration_precedence(system=system, contract=contract, customer=customer)
    return {
        "managed_configuration_version": MANAGED_CONFIGURATION_VERSION,
        "kind": "ManagedConfiguration",
        "effective": resolved["effective"],
        "provenance": resolved["provenance"],
        "conflicts": resolved["conflicts"],
        "precedence": resolved["precedence"],
    }
