#!/usr/bin/env python3
"""Transactional core for a future NeoForge + Server Pack migration executor.

This module defines sequencing, evidence binding and compensation only. It is
not wired to provisioning yet and performs no filesystem/runtime mutation by
itself; concrete Agent hooks must be supplied by the caller.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from minecraft_serverpack_migration_contract import (
    validate_minecraft_serverpack_migration,
)
from runtime_operations import runtime_operation


class MinecraftServerPackMigrationExecutionError(RuntimeError):
    def __init__(self, message: str, trace: tuple[str, ...] = ()):
        super().__init__(message)
        self.trace = trace


_REQUIRED_HOOKS = (
    "revalidate",
    "capacity",
    "backup",
    "stop",
    "stage",
    "swap",
    "readiness",
    "commit",
    "rollback",
)


def _hooks(value: Mapping[str, Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    if not isinstance(value, Mapping):
        raise MinecraftServerPackMigrationExecutionError("migration hooks are required")
    result: dict[str, Callable[..., Any]] = {}
    for name in _REQUIRED_HOOKS:
        callback = value.get(name)
        if not callable(callback):
            raise MinecraftServerPackMigrationExecutionError(
                f"migration hook is missing: {name}"
            )
        result[name] = callback
    return result


def _verified_backup(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MinecraftServerPackMigrationExecutionError(
            "pre-update backup evidence is invalid"
        )
    backup_id = str(value.get("backup_id") or "").strip()
    sha256 = str(value.get("sha256") or "").strip().lower()
    try:
        size = int(value.get("size_bytes") or 0)
    except (TypeError, ValueError):
        size = 0
    if (
        not backup_id
        or len(sha256) != 64
        or any(c not in "0123456789abcdef" for c in sha256)
        or size <= 0
        or value.get("integrity_verified") is not True
    ):
        raise MinecraftServerPackMigrationExecutionError(
            "pre-update backup must be independently verified"
        )
    return {
        "backup_id": backup_id,
        "sha256": sha256,
        "size_bytes": size,
        "integrity_verified": True,
    }


def execute_minecraft_serverpack_migration(
    config: dict[str, Any],
    instance_id: str,
    migration: Mapping[str, Any],
    hooks: Mapping[str, Callable[..., Any]],
    *,
    lock_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Run the transaction against caller-owned concrete Agent hooks.

    Ordering is fixed: validate -> re-attest -> capacity -> backup -> stop ->
    stage -> swap -> readiness -> commit. Any failure after staging begins
    invokes rollback exactly once while the exclusive runtime-operation lock is
    still held. A rollback failure is terminal and requires manual recovery.
    """
    evidence = validate_minecraft_serverpack_migration(
        migration, instance_id=instance_id
    )
    callbacks = _hooks(hooks)
    trace: list[str] = ["contract_validated"]
    backup: dict[str, Any] | None = None
    mutated = False

    with runtime_operation(
        config,
        instance_id,
        "minecraft_serverpack_migration",
        lock_timeout_seconds=lock_timeout_seconds,
    ):
        current = callbacks["revalidate"](dict(evidence))
        if not isinstance(current, Mapping):
            raise MinecraftServerPackMigrationExecutionError(
                "migration revalidation returned invalid evidence", tuple(trace)
            )
        if current.get("valid") is not True or current.get("install_allowed") is not False:
            raise MinecraftServerPackMigrationExecutionError(
                "migration preview is no longer valid", tuple(trace)
            )
        if str(current.get("migration_plan_sha256") or "").strip().lower() != evidence["migration_plan_sha256"]:
            raise MinecraftServerPackMigrationExecutionError(
                "migration fingerprint changed under lock", tuple(trace)
            )
        trace.append("revalidated")

        capacity = callbacks["capacity"](dict(evidence))
        if (
            not isinstance(capacity, Mapping)
            or capacity.get("sufficient") is not True
            or capacity.get("install_allowed") is not False
            or capacity.get("requires_exclusive_recheck") is not True
        ):
            raise MinecraftServerPackMigrationExecutionError(
                "exclusive migration capacity check failed", tuple(trace)
            )
        trace.append("capacity_checked")

        backup = _verified_backup(callbacks["backup"](dict(evidence)))
        trace.append("backup_verified")

        try:
            callbacks["stop"](dict(evidence), dict(backup))
            trace.append("stopped")
            callbacks["stage"](dict(evidence), dict(backup))
            trace.append("staged")
            mutated = True
            callbacks["swap"](dict(evidence), dict(backup))
            trace.append("swapped")
            ready = callbacks["readiness"](dict(evidence), dict(backup))
            if ready is not True:
                raise MinecraftServerPackMigrationExecutionError(
                    "new loader or Server Pack failed readiness", tuple(trace)
                )
            trace.append("ready")
            commit = callbacks["commit"](dict(evidence), dict(backup))
            trace.append("committed")
            return {
                "kind": "MinecraftServerPackMigrationResult",
                "status": "completed",
                "instance_id": evidence["instance_id"],
                "content_id": evidence["content_id"],
                "transfer_id": evidence["transfer_id"],
                "migration_plan_sha256": evidence["migration_plan_sha256"],
                "from_loader_version": evidence["from_loader_version"],
                "target_loader_version": evidence["target_loader_version"],
                "backup": dict(backup),
                "commit": dict(commit) if isinstance(commit, Mapping) else {},
                "trace": trace,
            }
        except Exception as exc:
            trace.append("failed")
            if mutated:
                try:
                    callbacks["rollback"](
                        dict(evidence),
                        dict(backup or {}),
                        tuple(trace),
                    )
                    trace.append("rolled_back")
                except Exception as rollback_exc:
                    trace.append("rollback_failed")
                    raise MinecraftServerPackMigrationExecutionError(
                        "migration failed and rollback also failed: manual recovery required",
                        tuple(trace),
                    ) from rollback_exc
            raise MinecraftServerPackMigrationExecutionError(
                "migration transaction stopped: " + str(exc), tuple(trace)
            ) from exc


__all__ = [
    "MinecraftServerPackMigrationExecutionError",
    "execute_minecraft_serverpack_migration",
]
