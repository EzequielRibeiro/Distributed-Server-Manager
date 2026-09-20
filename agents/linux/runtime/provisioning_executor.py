#!/usr/bin/env python3
"""Execute one provisioning pipeline locally on the owning Linux Agent."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
from typing import Any

from game_data_executor import _execute as execute_game_data
from backup_client import _create as create_backup
import game_runtime
import instance_runtime
import privileged_materialization
import privileged_firewall
import runtime_materialization
from provisioning_contract import validate_provisioning_request
from provisioning_state import write_json
from runtime_events import emit_runtime_event
from runtime_limits import runtime_limits
from runtime_metrics import increment, observe_duration
from runtime_operations import runtime_operation


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(\b(?:password|passwd|token|secret|api[_-]?key|steam[_-]?(?:password|token|guard))\b"
        r"\s*(?::|=)\s*)[^\s,;]+"
    ),
    re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|password|secret)=)[^&#\s]+"),
)


def _sanitize_failure_text(value: Any, *, limit: int) -> str:
    """Redact common credentials and normalize sensitive host paths."""
    text = str(value or "").replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = re.sub(r"(?i)(\+login\s+)\S+(?:\s+\S+)?", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)/opt/dsm/", "<DSM_ROOT>/", text)
    text = re.sub(r"(?i)/home/[^/\s]+/", "<HOME>/", text)
    text = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s]+\\", "<USER_HOME>/", text)
    return text[:limit]


def _failure_diagnostics(request: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """Build a bounded diagnostic payload safe enough to leave the Agent."""
    return {
        "error": _sanitize_failure_text(exc, limit=2000),
        "exception_type": type(exc).__name__[:256],
        "traceback": _sanitize_failure_text(traceback.format_exc(limit=32), limit=16000),
        "source": "agent.provisioning_executor",
        "failed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "correlation_id": str(request.get("provisioning_id") or "")[:256],
    }


def _workspace(instance_id: str) -> Path:
    base = Path(os.environ.get("CAPIVARA_INSTANCE_WORKSPACE_ROOT", str(Path(instance_runtime.STATE_DIR) / "instance-workspaces")))
    root = (base / instance_id).resolve()
    root.relative_to(base.resolve())
    return root


def _prepare_workspace(instance_id: str) -> dict[str, str]:
    root = _workspace(instance_id)
    paths = {"root": root, "staging": root / "staging", "config": root / "config", "runtime": root / "runtime"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return {key: str(value) for key, value in paths.items()}


def _result(path: Path, request: dict[str, Any], *, status: str, current_step: str, progress: int, **extra: Any) -> dict[str, Any]:
    payload = {"provisioning_id": request["provisioning_id"], "instance_id": request["instance_id"],
               "status": status, "current_step": current_step, "progress": progress, **extra}
    write_json(path, payload)
    return payload


def _event(event_type: str, request: dict[str, Any], *, step: str, progress: int, data: dict[str, Any] | None = None) -> None:
    emit_runtime_event(Path(instance_runtime.STATE_DIR), event_type, instance_id=request["instance_id"], agent_id=request["agent_id"],
                       data={"provisioning_id": request["provisioning_id"], "step": step, "progress": progress, **dict(data or {})})


def _check_deadline(deadline: float, step: str) -> None:
    if time.monotonic() > deadline:
        raise TimeoutError(f"provisioning timeout exceeded during {step}")


def _execute_locked(config: dict[str, Any], request: dict[str, Any], result_path: Path, deadline: float) -> dict[str, Any]:
    step = "accepted"
    materialized = False
    workspace: dict[str, str] | None = None
    content_result: dict[str, Any] | None = None
    compensation: list[str] = []
    configuration = dict(request.get("configuration") or {})
    update_meta = configuration.get("minecraft_version_update") if isinstance(configuration.get("minecraft_version_update"), dict) else None
    previous_runtime = instance_runtime.get_instance(request["instance_id"]) if update_meta else None
    update_was_running = False
    update_backup: dict[str, Any] | None = None
    update_stopped = False
    if update_meta and previous_runtime is None:
        raise RuntimeError("Minecraft version update requires an existing instance runtime")
    _result(result_path, request, status="running", current_step=step, progress=5)
    _event("INSTANCE_PROVISIONING_STARTED", request, step=step, progress=5)
    try:
        step = "prepare_workspace"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=15)
        workspace = _prepare_workspace(request["instance_id"])
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=15)

        step = "validate_ports"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=25)
        ports = dict(request["ports"])
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=25, data={"port_roles": sorted(ports)})

        step = "install_content"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=35)
        content_result = execute_game_data({"action": request["content"]["action"], "selection": dict(request["content"]["selection"])})
        _check_deadline(deadline, step)
        install_path = str(content_result["target_path"])
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=60, data={"provider": content_result.get("provider")})

        if update_meta:
            step = "backup_current_runtime"; _check_deadline(deadline, step)
            _result(result_path, request, status="running", current_step=step, progress=64)
            update_was_running = instance_runtime.status(config, request["instance_id"]).get("observed_state") == "running"
            if bool(update_meta.get("backup_before_update", True)):
                update_backup = create_backup(
                    config,
                    {
                        "instance_id": request["instance_id"],
                        "policy": {
                            "mode": "full",
                            "compression": "gzip",
                            "retention_count": 7,
                            "consistency": "stopped",
                        },
                    },
                )
            if update_was_running:
                instance_runtime.lifecycle(config, request["instance_id"], "stop")
                update_stopped = True
            _event(
                "INSTANCE_PROVISIONING_STEP",
                request,
                step=step,
                progress=66,
                data={"backup_id": (update_backup or {}).get("backup_id"), "was_running": update_was_running},
            )

        step = "build_runtime_spec"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=70)
        context = dict(configuration)
        context["install_path"] = install_path; context["content_root"] = install_path; context["ports"] = ports
        instance = dict(request["instance"])
        spec = game_runtime.build_runtime_spec(config, instance, context)
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=75, data={"profile": spec.get("profile")})

        step = "materialize_runtime"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=82)
        materialization = privileged_materialization.materialize(config, spec)
        materialized = True
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=88, data={"adapter": spec.get("adapter")})

        step = "apply_firewall"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=90)
        firewall = privileged_firewall.reconcile(spec)
        _event(
            "INSTANCE_PROVISIONING_STEP",
            request,
            step=step,
            progress=90,
            data={
                "backend": firewall.get("backend"),
                "changed": bool(firewall.get("changed")),
            },
        )

        step = "initial_reconcile"; _check_deadline(deadline, step)
        _result(result_path, request, status="running", current_step=step, progress=92)
        reconciliation = runtime_materialization.reconcile(config, request["instance_id"])
        _check_deadline(deadline, step)
        observed_state = str(reconciliation.get("observed_state") or "unknown")
        update_readiness = None
        if update_meta:
            step = "update_readiness"; _check_deadline(deadline, step)
            _result(result_path, request, status="running", current_step=step, progress=96)
            update_readiness = instance_runtime.doctor(config, request["instance_id"])
            if not bool(update_readiness.get("ready")):
                raise RuntimeError("updated Minecraft runtime failed readiness validation")
            _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=97, data={"readiness": update_readiness.get("status")})
        final = _result(result_path, request, status="completed", current_step="completed", progress=100,
                        desired_state=request["desired_state"], observed_state=observed_state, workspace=workspace,
                        content={"provider": content_result.get("provider"), "game": content_result.get("game"),
                                 "version": content_result.get("version"), "target_path": content_result.get("target_path")},
                        runtime={"profile": spec.get("profile"), "profile_version": spec.get("profile_version"),
                                 "adapter": spec.get("adapter"), "runtime_id": spec.get("runtime_id"),
                                 "materialized_changed": bool((materialization.get("operation") or {}).get("changed"))},
                        minecraft_version_update={
                            "target_version": update_meta.get("target_version"),
                            "target_build": update_meta.get("target_build"),
                            "backup_id": (update_backup or {}).get("backup_id"),
                            "isolated_install_dir": update_meta.get("isolated_install_dir"),
                            "readiness": (update_readiness or {}).get("status"),
                        } if update_meta else None)
        increment("provisioning_completed")
        _event("INSTANCE_PROVISIONING_COMPLETED", request, step="completed", progress=100,
               data={"desired_state": request["desired_state"], "observed_state": observed_state})
        return final
    except Exception as exc:
        if update_meta and previous_runtime is not None:
            try:
                if materialized:
                    try:
                        current = instance_runtime.status(config, request["instance_id"])
                        if current.get("observed_state") == "running":
                            instance_runtime.lifecycle(config, request["instance_id"], "stop")
                    except Exception:
                        pass
                    restored = dict(previous_runtime)
                    restored["desired_state"] = "running" if update_was_running else str(previous_runtime.get("desired_state") or "stopped")
                    privileged_materialization.materialize(config, restored)
                    if isinstance(restored.get("catalog_runtime_policy"), dict):
                        privileged_firewall.reconcile(restored)
                    runtime_materialization.reconcile(config, request["instance_id"])
                    compensation.append("previous_runtime_restored")
                elif update_stopped and update_was_running:
                    instance_runtime.lifecycle(config, request["instance_id"], "start")
                    compensation.append("previous_runtime_restarted")
            except Exception:
                compensation.append("runtime_rollback_failed")
        elif materialized:
            try:
                cleanup = privileged_materialization.remove(config, request["instance_id"])
                if isinstance(cleanup, dict) and cleanup.get("firewall") is not None:
                    compensation.append("firewall_removed")
                compensation.append("runtime_removed")
            except Exception:
                compensation.append("runtime_cleanup_failed")
        if workspace:
            staging = Path(workspace["staging"])
            try:
                shutil.rmtree(staging); staging.mkdir(parents=True, exist_ok=True); compensation.append("staging_cleaned")
            except OSError:
                compensation.append("staging_cleanup_failed")
        compensation.extend(["content_preserved_for_retry", "port_reservations_preserved"])
        increment("provisioning_failed")
        diagnostics = _failure_diagnostics(request, exc)
        failed = _result(result_path, request, status="failed", current_step=step, progress=99,
                         compensation=compensation, **diagnostics)
        _event("INSTANCE_PROVISIONING_FAILED", request, step=step, progress=99,
               data={"error": diagnostics["error"], "exception_type": diagnostics["exception_type"],
                     "correlation_id": diagnostics["correlation_id"], "compensation": compensation})
        return failed


def execute(config: dict[str, Any], request: dict[str, Any], result_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    try:
        request = validate_provisioning_request(request, expected_agent_id=str(config.get("agent_id") or ""))
    except Exception as exc:
        increment("provisioning_contract_failure")
        diagnostics = _failure_diagnostics(request, exc)
        failed = _result(
            result_path,
            request,
            status="failed",
            current_step="validate_contract",
            progress=99,
            compensation=["content_preserved_for_retry", "port_reservations_preserved"],
            **diagnostics,
        )
        _event(
            "INSTANCE_PROVISIONING_FAILED",
            request,
            step="validate_contract",
            progress=99,
            data={
                "error": diagnostics["error"],
                "exception_type": diagnostics["exception_type"],
                "correlation_id": diagnostics["correlation_id"],
            },
        )
        observe_duration("provisioning", int((time.monotonic() - started) * 1000))
        return failed
    limits = runtime_limits(config)
    deadline = started + limits.provisioning_timeout_seconds
    try:
        with runtime_operation(config, request["instance_id"], "provision", lock_timeout_seconds=limits.lock_timeout_seconds):
            result = _execute_locked(config, request, result_path, deadline)
    except Exception as exc:
        increment("provisioning_conflict_or_failure")
        diagnostics = _failure_diagnostics(request, exc)
        result = _result(result_path, request, status="failed", current_step="operation_lock", progress=99,
                         compensation=["content_preserved_for_retry", "port_reservations_preserved"], **diagnostics)
        _event("INSTANCE_PROVISIONING_FAILED", request, step="operation_lock", progress=99,
               data={"error": diagnostics["error"], "exception_type": diagnostics["exception_type"],
                     "correlation_id": diagnostics["correlation_id"]})
    observe_duration("provisioning", int((time.monotonic() - started) * 1000))
    return result


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: provisioning_executor.py CONFIG REQUEST RESULT", file=sys.stderr); return 2
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    request = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    result = execute(config, request, Path(sys.argv[3]))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
