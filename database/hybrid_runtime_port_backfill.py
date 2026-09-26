#!/usr/bin/env python3
"""Controller-authoritative port backfill for persisted Hybrid RuntimeSpecs."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT_DIR / "dashboard"
for module_dir in (ROOT_DIR, ROOT_DIR / "database", DASHBOARD_DIR):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from customer_instance_creation import runtime_definition
from instance_network import occupied_ports_provider_for_backend
from instance_port_reconcile import reconcile_instance_ports
from instance_workspace_repository import InstanceWorkspaceRepository

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")


class HybridRuntimePortBackfillError(RuntimeError):
    """A Hybrid RuntimeSpec cannot be reconciled with Controller reservations."""


def _runtime_specs_root(root: Path) -> Path:
    return Path(root) / "runtime" / "hybrid-agent-state" / "instances"


def _read_spec(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HybridRuntimePortBackfillError(
            f"Hybrid RuntimeSpec cannot be read: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise HybridRuntimePortBackfillError(
            f"Hybrid RuntimeSpec must be an object: {path.name}"
        )
    return value


def _write_spec(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace one Agent-owned RuntimeSpec while preserving ownership."""
    try:
        metadata = path.stat()
    except OSError as exc:
        raise HybridRuntimePortBackfillError(
            f"Hybrid RuntimeSpec metadata cannot be read: {path.name}"
        ) from exc

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    except OSError as exc:
        raise HybridRuntimePortBackfillError(
            f"Hybrid RuntimeSpec cannot be persisted: {path.name}"
        ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _bindings_from_reservations(
    network_profile: Mapping[str, Any],
    reservations: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    requirements = network_profile.get("ports")
    if not isinstance(requirements, list) or not requirements:
        raise HybridRuntimePortBackfillError(
            "runtime network profile has no port requirements"
        )

    bindings: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            raise HybridRuntimePortBackfillError(
                "runtime network profile has an invalid port requirement"
            )
        name = str(requirement.get("name") or "").strip().lower()
        protocol = str(requirement.get("protocol") or "").strip().lower()
        if not name or protocol not in {"tcp", "udp"}:
            raise HybridRuntimePortBackfillError(
                "runtime network profile has an invalid port requirement"
            )
        if name not in reservations:
            raise HybridRuntimePortBackfillError(
                f"Controller reservation result is missing port role: {name}"
            )
        try:
            port = int(reservations[name])
        except (TypeError, ValueError) as exc:
            raise HybridRuntimePortBackfillError(
                f"Controller reservation result has an invalid port for role: {name}"
            ) from exc
        if not 1 <= port <= 65535:
            raise HybridRuntimePortBackfillError(
                f"Controller reservation result has an invalid port for role: {name}"
            )
        bindings[name] = {"port": port, "protocol": protocol}
    return bindings


def _network_variable_template(value: Any) -> str:
    """Translate Catalog {role} placeholders to persisted Agent variables."""
    return re.sub(
        r"\{([a-z][a-z0-9_]{0,63})\}",
        lambda match: "{{PORT_" + match.group(1).upper() + "}}",
        str(value),
    )


def _canonical_network_state(
    network_profile: Mapping[str, Any],
    bindings: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    exposure: list[dict[str, str]] = []
    requirements = network_profile.get("ports")
    if not isinstance(requirements, list):
        requirements = []
    for item in requirements:
        if not isinstance(item, Mapping):
            continue
        exposure.append(
            {
                "name": str(item.get("name") or "").strip(),
                "protocol": str(item.get("protocol") or "").strip().lower(),
                "exposure": str(item.get("exposure") or "none").strip().lower(),
            }
        )

    properties: list[dict[str, str]] = []
    applications = network_profile.get("apply")
    if not isinstance(applications, list):
        applications = []
    for item in applications:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("kind") or "").strip().lower() != "property":
            continue
        properties.append(
            {
                "path": str(item.get("file") or "").strip(),
                "key": str(item.get("key") or "").strip(),
                "value": _network_variable_template(item.get("value") or ""),
                "syntax": str(item.get("syntax") or "equals").strip().lower(),
            }
        )

    variables = {
        "PORT_" + str(name).upper().replace("-", "_"): str(binding["port"])
        for name, binding in bindings.items()
    }
    if "PORT_STEAM_QUERY" not in variables and "PORT_GAME_AUX" in variables:
        variables["PORT_STEAM_QUERY"] = variables["PORT_GAME_AUX"]
    return exposure, properties, variables


def reconcile_hybrid_runtime_ports(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    """Backfill DB reservations first, then persist canonical bindings locally.

    This function deliberately performs no runtime lifecycle action. Any failure is
    propagated so the caller can stop before RuntimeSpec migration/reconciliation.
    """
    specs_root = _runtime_specs_root(root)
    if not specs_root.exists():
        return {
            "status": "completed",
            "instances": 0,
            "networked": 0,
            "reservations_backfilled": 0,
            "specs_updated": 0,
        }

    repository = InstanceWorkspaceRepository(backend)
    repository.initialize()
    occupied_ports_provider = occupied_ports_provider_for_backend(backend)

    instances = 0
    networked = 0
    reservations_backfilled = 0
    specs_updated = 0

    try:
        paths = sorted(specs_root.glob("*.json"))
    except OSError as exc:
        raise HybridRuntimePortBackfillError(
            "Hybrid RuntimeSpec inventory cannot be listed"
        ) from exc

    for path in paths:
        record = _read_spec(path)
        if str(record.get("agent_id") or "").strip() != str(agent_id):
            continue

        instance_id = str(record.get("instance_id") or "").strip()
        if not _TOKEN.fullmatch(instance_id):
            raise HybridRuntimePortBackfillError(
                f"Hybrid RuntimeSpec has invalid instance identity: {path.name}"
            )
        if path.stem != instance_id:
            raise HybridRuntimePortBackfillError(
                f"Hybrid RuntimeSpec filename does not match instance identity: {path.name}"
            )
        instances += 1

        try:
            context = repository.instance_context(instance_id)
        except (KeyError, ValueError) as exc:
            raise HybridRuntimePortBackfillError(
                f"Controller instance state is unavailable: {instance_id}"
            ) from exc
        if str(context.get("agent_id") or "").strip() != str(agent_id):
            raise HybridRuntimePortBackfillError(
                f"Controller instance is not bound to this Hybrid Agent: {instance_id}"
            )

        game_id = str(
            record.get("game_id") or context.get("game_id") or ""
        ).strip().lower()
        runtime_id = str(
            record.get("environment_id")
            or context.get("runtime_id")
            or context.get("environment_id")
            or ""
        ).strip()

        # Generic pre-profile RuntimeSpecs have no Catalog identity and therefore
        # no Controller network profile to reconcile. Once either identity exists,
        # the pair must be complete; guessing would violate fail-closed semantics.
        if not game_id and not runtime_id:
            continue
        if not game_id or not runtime_id:
            raise HybridRuntimePortBackfillError(
                f"Catalog runtime identity is incomplete for instance: {instance_id}"
            )

        try:
            definition = runtime_definition(Path(root), game_id, runtime_id)
        except (OSError, ValueError) as exc:
            raise HybridRuntimePortBackfillError(
                f"Catalog runtime definition is unavailable for instance: {instance_id}"
            ) from exc
        network_profile = definition.get("network")
        if not isinstance(network_profile, Mapping):
            continue
        networked += 1

        # The database transaction and collision checks are authoritative. Never
        # synthesize ports from offsets in Agent-local state.
        try:
            runtime_stopped_proof = (
                str(record.get("desired_state") or "").strip().lower() == "stopped"
                and str(record.get("observed_state") or "").strip().lower() == "stopped"
            )
            result = reconcile_instance_ports(
                repository,
                instance_id,
                network_profile,
                occupied_ports_provider=occupied_ports_provider,
                runtime_stopped_proof=runtime_stopped_proof,
            )
        except Exception as exc:
            raise HybridRuntimePortBackfillError(
                f"Controller port reconciliation failed for instance: {instance_id}: {exc}"
            ) from exc

        reservations = result.get("ports")
        if not isinstance(reservations, Mapping):
            raise HybridRuntimePortBackfillError(
                f"Controller port reconciliation returned an invalid result: {instance_id}"
            )
        bindings = _bindings_from_reservations(network_profile, reservations)
        if bool(result.get("changed")):
            reservations_backfilled += 1

        updated = dict(record)
        profile_context = updated.get("profile_context")
        if not isinstance(profile_context, dict):
            profile_context = {}
        else:
            profile_context = dict(profile_context)

        exposure, properties, port_variables = _canonical_network_state(
            network_profile,
            bindings,
        )
        runtime_policy = updated.get("catalog_runtime_policy")
        if isinstance(runtime_policy, dict):
            runtime_policy = dict(runtime_policy)
            runtime_policy["network_exposure"] = exposure
            updated["catalog_runtime_policy"] = runtime_policy

        context_policy = profile_context.get("catalog_runtime_policy")
        if isinstance(context_policy, dict):
            context_policy = dict(context_policy)
        elif isinstance(runtime_policy, dict):
            context_policy = dict(runtime_policy)
        else:
            context_policy = None
        if isinstance(context_policy, dict):
            context_policy["network_exposure"] = exposure
            context_policy["network_properties"] = properties
            profile_context["catalog_runtime_policy"] = context_policy

        variables = updated.get("catalog_variables")
        variables = dict(variables) if isinstance(variables, dict) else {}
        variables = {
            str(key): value
            for key, value in variables.items()
            if not str(key).startswith("PORT_")
        }
        variables.update(port_variables)

        changed = (
            updated.get("ports") != bindings
            or profile_context.get("ports") != bindings
            or (
                isinstance(record.get("catalog_runtime_policy"), dict)
                and record["catalog_runtime_policy"].get("network_exposure") != exposure
            )
            or updated.get("catalog_network_properties") != properties
            or updated.get("catalog_variables") != variables
            or (
                isinstance(record.get("profile_context"), dict)
                and isinstance(record["profile_context"].get("catalog_runtime_policy"), dict)
                and record["profile_context"]["catalog_runtime_policy"] != profile_context.get("catalog_runtime_policy")
            )
        )
        updated["ports"] = bindings
        profile_context["ports"] = bindings
        updated["profile_context"] = profile_context
        updated["catalog_network_properties"] = properties
        updated["catalog_variables"] = variables
        if changed:
            _write_spec(path, updated)
            specs_updated += 1

    return {
        "status": "completed",
        "instances": instances,
        "networked": networked,
        "reservations_backfilled": reservations_backfilled,
        "specs_updated": specs_updated,
    }


__all__ = [
    "HybridRuntimePortBackfillError",
    "reconcile_hybrid_runtime_ports",
]
