"""Canonical SYSTEM > CONTRACT > CUSTOMER precedence for Capivara DSM P0-G."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

POLICY_VERSION = 1
KIND = "ConfigurationPrecedence"
EFFECTIVE_KIND = "EffectiveConfiguration"
PRECEDENCE = ("SYSTEM", "CONTRACT", "CUSTOMER")


class ConfigurationPrecedenceError(ValueError):
    """Raised when precedence input is structurally invalid."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationPrecedenceError(f"{field} must be an object")
    for key in value:
        if not isinstance(key, str) or not key:
            raise ConfigurationPrecedenceError(f"{field} keys must be non-empty strings")
    return value


def validate_precedence_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the portable layer document; layer order itself is not authoritative."""
    doc = _mapping(document, "document")
    if doc.get("policy_version") != POLICY_VERSION:
        raise ConfigurationPrecedenceError("unsupported policy_version")
    if doc.get("kind") != KIND:
        raise ConfigurationPrecedenceError("kind must be ConfigurationPrecedence")
    layers = doc.get("layers")
    if not isinstance(layers, list):
        raise ConfigurationPrecedenceError("layers must be an array")

    seen: set[str] = set()
    for index, layer in enumerate(layers):
        item = _mapping(layer, f"layers[{index}]")
        source = str(item.get("source") or "").strip().upper()
        if source not in PRECEDENCE:
            raise ConfigurationPrecedenceError(f"unknown source: {source or '<empty>'}")
        if source in seen:
            raise ConfigurationPrecedenceError(f"duplicate source: {source}")
        seen.add(source)
        _mapping(item.get("values"), f"layers[{index}].values")
    return deepcopy(dict(doc))


def _resolve_node(nodes: list[tuple[str, Any]], path: str) -> tuple[Any, Any, list[dict[str, Any]]]:
    """Resolve one key. Highest present layer defines type; maps merge recursively."""
    if not nodes:
        raise ConfigurationPrecedenceError("cannot resolve an empty node set")

    rank = {source: index for index, source in enumerate(PRECEDENCE)}
    nodes = sorted(nodes, key=lambda item: rank[item[0]])
    winner_source, winner_value = nodes[0]

    conflicts: list[dict[str, Any]] = []
    if len(nodes) > 1:
        conflicts.append(
            {
                "path": path,
                "winner": winner_source,
                "shadowed": [source for source, _ in nodes[1:]],
            }
        )

    if not isinstance(winner_value, Mapping):
        return deepcopy(winner_value), winner_source, conflicts

    # A higher-precedence object owns the container type. Lower scalar/list values
    # cannot replace it, while lower objects may fill keys absent above them.
    object_nodes = [(source, value) for source, value in nodes if isinstance(value, Mapping)]
    keys: set[str] = set()
    for _, value in object_nodes:
        _mapping(value, path or "values")
        keys.update(value.keys())

    effective: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    nested_conflicts: list[dict[str, Any]] = []
    for key in sorted(keys):
        child_nodes = [(source, value[key]) for source, value in object_nodes if key in value]
        child_path = f"{path}.{key}" if path else key
        child_effective, child_provenance, child_conflicts = _resolve_node(child_nodes, child_path)
        effective[key] = child_effective
        provenance[key] = child_provenance
        nested_conflicts.extend(child_conflicts)
    return effective, provenance, conflicts + nested_conflicts


def resolve_precedence_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a layer document into effective values plus per-key provenance."""
    checked = validate_precedence_document(document)
    by_source = {str(layer["source"]).upper(): layer["values"] for layer in checked["layers"]}
    root_nodes = [(source, by_source[source]) for source in PRECEDENCE if source in by_source]

    if not root_nodes:
        effective: dict[str, Any] = {}
        provenance: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
    else:
        effective, provenance, conflicts = _resolve_node(root_nodes, "")

    # The root is always a map because layer values are required to be maps.
    return {
        "policy_version": POLICY_VERSION,
        "kind": EFFECTIVE_KIND,
        "precedence": list(PRECEDENCE),
        "effective": effective,
        "provenance": provenance,
        "conflicts": [item for item in conflicts if item["path"]],
    }


def resolve_configuration_precedence(
    *,
    system: Mapping[str, Any] | None = None,
    contract: Mapping[str, Any] | None = None,
    customer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience API used by Controller/Managed Configuration callers."""
    layers = []
    for source, values in (
        ("SYSTEM", system),
        ("CONTRACT", contract),
        ("CUSTOMER", customer),
    ):
        if values is not None:
            layers.append({"source": source, "values": dict(_mapping(values, source.lower()))})
    return resolve_precedence_document(
        {"policy_version": POLICY_VERSION, "kind": KIND, "layers": layers}
    )
