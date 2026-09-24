"""Execute a complete provisioning pipeline on the owning Windows Agent."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from backup_client import _create as create_backup
from game_data_executor import execute as execute_game_data
import game_runtime
import instance_runtime
import runtime_materialization
from provisioning_state import write_json
from runtime_events import emit_runtime_event
from runtime_metrics import increment

PROGRAM_STEP_TIMEOUT = 7200


def _event(event_type: str, instance: dict[str, Any], request: dict[str, Any], data: dict[str, Any] | None = None) -> None:
    emit_runtime_event(
        Path(instance_runtime.STATE_DIR),
        event_type,
        agent_id=instance["agent_id"],
        instance_id=instance["instance_id"],
        data={"provisioning_id": request["provisioning_id"], **dict(data or {})},
    )


def _result(path: Path, req: dict[str, Any], *, status: str, current_step: str, progress: int, **extra: Any) -> dict[str, Any]:
    payload = {
        "provisioning_id": req["provisioning_id"],
        "instance_id": req["instance_id"],
        "status": status,
        "current_step": current_step,
        "progress": progress,
        **extra,
    }
    write_json(path, payload)
    return payload


def _validate(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    for key in ("provisioning_id", "instance_id"):
        if not str(request.get(key) or "").strip():
            raise ValueError(f"{key} is required")
    agent = str(config.get("agent_id") or "").strip()
    requested = str(request.get("agent_id") or agent).strip()
    if not agent or requested != agent:
        raise PermissionError("provisioning belongs to another Agent")
    instance = request.get("instance")
    if not isinstance(instance, dict):
        raise ValueError("instance is required")
    reserved = instance.get("storage_reserved_bytes")
    if reserved is not None:
        try:
            reserved = int(reserved)
        except (TypeError, ValueError) as exc:
            raise ValueError("storage_reserved_bytes must be an integer") from exc
        if reserved < 0:
            raise ValueError("storage_reserved_bytes cannot be negative")
        if reserved > 0 and not str(instance.get("storage_pool_id") or "").strip():
            raise ValueError("positive storage reservation requires storage_pool_id")
    return {
        **instance,
        "instance_id": request["instance_id"],
        "agent_id": agent,
        "desired_state": request.get("desired_state") or instance.get("desired_state") or "stopped",
    }


def execute(config: dict[str, Any], request: dict[str, Any], result_path: Path) -> dict[str, Any]:
    instance = _validate(config, request)
    step = "accepted"
    started = time.monotonic()
    materialized = False
    compensation: list[str] = []
    configuration = request.get("configuration") if isinstance(request.get("configuration"), dict) else {}
    version_update_meta = configuration.get("minecraft_version_update") if isinstance(configuration.get("minecraft_version_update"), dict) else None
    migration_meta = configuration.get("minecraft_runtime_migration") if isinstance(configuration.get("minecraft_runtime_migration"), dict) else None
    update_meta = migration_meta or version_update_meta
    previous_runtime = instance_runtime.get_instance(instance["instance_id"]) if update_meta else None
    update_was_running = False
    update_stopped = False
    update_backup: dict[str, Any] | None = None
    if update_meta and previous_runtime is None:
        raise RuntimeError("Minecraft runtime change requires an existing instance runtime")

    _result(result_path, request, status="running", current_step=step, progress=5)
    _event("INSTANCE_PROVISIONING_STARTED", instance, request)
    try:
        step = "install_content"
        _result(result_path, request, status="running", current_step=step, progress=25)
        content = request.get("content") if isinstance(request.get("content"), dict) else {}
        selection = content.get("selection") if isinstance(content.get("selection"), dict) else None
        if selection is not None:
            content_result = execute_game_data({"action": content.get("action") or "install", "selection": selection})
        else:
            install_path = str(configuration.get("install_path") or instance.get("path") or "").strip()
            if not install_path:
                raise ValueError("provisioning content selection or install_path is required")
            content_result = {"provider": "preinstalled", "game": instance.get("game_id"), "version": None, "target_path": install_path}

        if time.monotonic() - started > PROGRAM_STEP_TIMEOUT:
            raise TimeoutError("provisioning timeout exceeded")

        if update_meta:
            step = "backup_current_runtime"
            _result(result_path, request, status="running", current_step=step, progress=60)
            update_was_running = instance_runtime.status(config, instance["instance_id"]).get("observed_state") == "running"
            if bool(update_meta.get("backup_before_update", True)):
                update_backup = create_backup(
                    config,
                    {
                        "instance_id": instance["instance_id"],
                        "policy": {
                            "mode": "full",
                            "compression": "gzip",
                            "retention_count": 7,
                            "consistency": "stopped",
                        },
                    },
                )
            if update_was_running:
                instance_runtime.lifecycle(config, instance["instance_id"], "stop")
                update_stopped = True
            _event(
                "INSTANCE_PROVISIONING_STEP",
                instance,
                request,
                {
                    "step": step,
                    "progress": 64,
                    "backup_id": (update_backup or {}).get("backup_id"),
                    "was_running": update_was_running,
                },
            )

        step = "build_runtime_spec"
        _result(result_path, request, status="running", current_step=step, progress=65)
        context = dict(configuration)
        context["install_path"] = content_result["target_path"]
        context["content_root"] = content_result["target_path"]
        context["ports"] = request.get("ports") or context.get("ports") or {}
        context["desired_state"] = instance.get("desired_state")
        if instance.get("storage_pool_id"):
            context["storage_pool_id"] = instance["storage_pool_id"]

        spec = game_runtime.build_runtime_spec(config, instance, context)

        step = "materialize_runtime"
        _result(result_path, request, status="running", current_step=step, progress=82)
        materialization = runtime_materialization.materialize(config, spec)
        materialized = True

        step = "initial_reconcile"
        _result(result_path, request, status="running", current_step=step, progress=92)
        reconciliation = runtime_materialization.reconcile(config, instance["instance_id"])
        observed = str(reconciliation.get("observed_state") or "unknown")

        update_readiness = None
        if update_meta:
            step = "update_readiness"
            _result(result_path, request, status="running", current_step=step, progress=96)
            update_readiness = instance_runtime.doctor(config, instance["instance_id"])
            if not bool(update_readiness.get("ready")):
                raise RuntimeError("changed Minecraft runtime failed readiness validation")

        final = _result(
            result_path,
            request,
            status="completed",
            current_step="completed",
            progress=100,
            desired_state=spec["desired_state"],
            observed_state=observed,
            content={
                "provider": content_result.get("provider"),
                "game": content_result.get("game"),
                "version": content_result.get("version"),
                "target_path": content_result.get("target_path"),
            },
            runtime={
                "profile": spec.get("profile"),
                "profile_version": spec.get("profile_version"),
                "adapter": spec.get("adapter"),
                "runtime_id": spec.get("runtime_id"),
                "storage_pool_id": spec.get("storage_pool_id"),
                "instance_state_root": spec.get("instance_state_root"),
                "materialized_changed": bool((materialization.get("operation") or {}).get("changed")),
            },
            minecraft_version_update={
                "target_version": version_update_meta.get("target_version"),
                "target_build": version_update_meta.get("target_build"),
                "backup_id": (update_backup or {}).get("backup_id"),
                "isolated_install_dir": version_update_meta.get("isolated_install_dir"),
                "readiness": (update_readiness or {}).get("status"),
            } if version_update_meta else None,
            minecraft_runtime_migration={
                "from_runtime_id": migration_meta.get("from_runtime_id"),
                "target_runtime_id": migration_meta.get("target_runtime_id"),
                "target_version": migration_meta.get("target_version"),
                "target_build": migration_meta.get("target_build"),
                "backup_id": (update_backup or {}).get("backup_id"),
                "isolated_install_dir": migration_meta.get("isolated_install_dir"),
                "readiness": (update_readiness or {}).get("status"),
            } if migration_meta else None,
        )
        increment("provisioning_completed")
        _event("INSTANCE_PROVISIONING_COMPLETED", instance, request, {"observed_state": observed, "storage_pool_id": spec.get("storage_pool_id")})
        return final
    except Exception as exc:
        if update_meta and previous_runtime is not None:
            try:
                if materialized:
                    try:
                        current = instance_runtime.status(config, instance["instance_id"])
                        if current.get("observed_state") == "running":
                            instance_runtime.lifecycle(config, instance["instance_id"], "stop")
                    except Exception:
                        pass
                    restored = dict(previous_runtime)
                    restored["desired_state"] = "running" if update_was_running else str(previous_runtime.get("desired_state") or "stopped")
                    runtime_materialization.materialize(config, restored)
                    runtime_materialization.reconcile(config, instance["instance_id"])
                    compensation.append("previous_runtime_restored")
                elif update_stopped and update_was_running:
                    instance_runtime.lifecycle(config, instance["instance_id"], "start")
                    compensation.append("previous_runtime_restarted")
            except Exception:
                compensation.append("runtime_rollback_failed")
        elif materialized:
            try:
                runtime_materialization.remove(config, instance["instance_id"])
                compensation.append("runtime_removed")
            except Exception:
                compensation.append("runtime_cleanup_failed")
        compensation.extend(["content_preserved_for_retry", "port_reservations_preserved"])
        increment("provisioning_failed")
        failed = _result(
            result_path,
            request,
            status="failed",
            current_step=step,
            progress=100,
            error=str(exc)[:2000],
            compensation=compensation,
        )
        _event("INSTANCE_PROVISIONING_FAILED", instance, request, {"error": str(exc)[:2000], "compensation": compensation})
        return failed


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    request = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    result = execute(config, request, Path(sys.argv[3]))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
