#!/usr/bin/env python3
"""Controller-authoritative port backfill for persisted Hybrid RuntimeSpecs."""

from __future__ import annotations

import json
import os
import re
import subprocess
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
    optional = [
        *network_profile.get("on_demand_ports", []),
        *network_profile.get("legacy_reservations", []),
    ]
    # A reserved optional or pre-upgrade role must not vanish during Hybrid
    # heartbeat reconciliation. Never synthesize an absent optional role.
    declared = [*requirements, *(item for item in optional
                                if isinstance(item, Mapping)
                                and str(item.get("name") or "") in reservations)]
    for requirement in declared:
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
        existing = bindings.get(name)
        if existing is not None:
            if existing != {"port": port, "protocol": protocol}:
                raise HybridRuntimePortBackfillError("conflicting declared network port role")
            continue
        bindings[name] = {"port": port, "protocol": protocol}
    return bindings


def reconcile_hybrid_runtime_ports(
    backend,
    root: Path,
    agent_id: str,
    *,
    only_instance_id: str | None = None,
) -> dict[str, Any]:
    """Backfill DB reservations first, then persist canonical bindings locally.

    This function deliberately performs no runtime lifecycle action. Any failure is
    propagated so the caller can stop before RuntimeSpec migration/reconciliation.
    """
    specs_root = _runtime_specs_root(root)
    if only_instance_id is not None and not _TOKEN.fullmatch(str(only_instance_id)):
        raise HybridRuntimePortBackfillError("invalid target instance id")
    if only_instance_id is not None and not (specs_root / f"{only_instance_id}.json").is_file():
        raise HybridRuntimePortBackfillError("target Hybrid RuntimeSpec is unavailable")
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
        if only_instance_id is not None and path.stem != only_instance_id:
            continue
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
            result = reconcile_instance_ports(
                repository,
                instance_id,
                network_profile,
                occupied_ports_provider=occupied_ports_provider,
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
        metadata = context.get("instance_metadata") or {}
        pending_drop = metadata.get("network_optional_pending_drop") if isinstance(metadata, dict) else None
        if isinstance(pending_drop, list) and "votifier" in pending_drop:
            if str(context.get("status") or "").lower() not in {"stopped", "offline"}:
                raise HybridRuntimePortBackfillError("cannot remove Votifier binding while instance is active")
            try:
                systemd = subprocess.run(
                    ["systemctl", "show", f"capivara-instance-{instance_id}.service",
                     "--property=ActiveState", "--property=LoadState", "--no-pager"],
                    capture_output=True, text=True, timeout=6, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise HybridRuntimePortBackfillError(
                    "instance lifecycle cannot be verified before Votifier release"
                ) from exc
            state = dict(line.split("=", 1) for line in systemd.stdout.splitlines() if "=" in line)
            if systemd.returncode != 0 or state.get("LoadState") != "loaded" or state.get("ActiveState") != "inactive":
                raise HybridRuntimePortBackfillError(
                    "managed instance unit must be loaded and inactive before Votifier release"
                )
            bindings.pop("votifier", None)
        if bool(result.get("changed")):
            reservations_backfilled += 1

        updated = dict(record)
        profile_context = updated.get("profile_context")
        if not isinstance(profile_context, dict):
            profile_context = {}
        else:
            profile_context = dict(profile_context)

        changed = updated.get("ports") != bindings or profile_context.get("ports") != bindings
        # A pre-change spec might still require Votifier for all Minecraft Java
        # runtimes. Refresh its exposure policy from the canonical Catalog.
        if network_profile.get("on_demand_ports") or network_profile.get("legacy_reservations"):
            required = list(network_profile.get("ports") or [])
            optional = list(network_profile.get("on_demand_ports") or [])
            exposure = [
                {"name": item["name"], "protocol": item["protocol"],
                 "exposure": item.get("exposure", "none"),
                 **({"optional": True} if is_optional else {})}
                for is_optional, group in ((False, required), (True, optional))
                for item in group
            ]
            old_policy = updated.get("catalog_runtime_policy")
            if isinstance(old_policy, dict):
                new_policy = dict(old_policy)
                new_policy["network_exposure"] = exposure
                if old_policy != new_policy:
                    changed = True
                    updated["catalog_runtime_policy"] = new_policy
            # The profile migration path reads persisted structured context,
            # not just the top-level policy. Keep its other executable/launch
            # configuration intact while replacing only network exposure.
            context_policy = profile_context.get("catalog_runtime_policy")
            if isinstance(context_policy, dict):
                new_context_policy = dict(context_policy)
                new_context_policy["network_exposure"] = exposure
                if context_policy != new_context_policy:
                    changed = True
                    profile_context["catalog_runtime_policy"] = new_context_policy
        updated["ports"] = bindings
        profile_context["ports"] = bindings
        updated["profile_context"] = profile_context
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
