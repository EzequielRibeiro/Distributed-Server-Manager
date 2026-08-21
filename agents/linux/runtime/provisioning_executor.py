#!/usr/bin/env python3
"""Execute one B10 provisioning pipeline locally on the owning Linux Agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from game_data_executor import _execute as execute_game_data
import game_runtime
import instance_runtime
import privileged_materialization
import runtime_materialization
from provisioning_contract import validate_provisioning_request
from provisioning_state import write_json
from runtime_events import emit_runtime_event


def _workspace(instance_id: str) -> Path:
    base = Path(
        os.environ.get(
            "CAPIVARA_INSTANCE_WORKSPACE_ROOT",
            str(Path(instance_runtime.STATE_DIR) / "instance-workspaces"),
        )
    )
    root = (base / instance_id).resolve()
    root.relative_to(base.resolve())
    return root


def _prepare_workspace(instance_id: str) -> dict[str, str]:
    root = _workspace(instance_id)
    paths = {
        "root": root,
        "staging": root / "staging",
        "config": root / "config",
        "runtime": root / "runtime",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return {key: str(value) for key, value in paths.items()}


def _result(path: Path, request: dict[str, Any], *, status: str, current_step: str, progress: int, **extra: Any) -> dict[str, Any]:
    payload = {
        "provisioning_id": request["provisioning_id"],
        "instance_id": request["instance_id"],
        "status": status,
        "current_step": current_step,
        "progress": progress,
        **extra,
    }
    write_json(path, payload)
    return payload


def _event(event_type: str, request: dict[str, Any], *, step: str, progress: int, data: dict[str, Any] | None = None) -> None:
    emit_runtime_event(
        Path(instance_runtime.STATE_DIR),
        event_type,
        instance_id=request["instance_id"],
        agent_id=request["agent_id"],
        data={
            "provisioning_id": request["provisioning_id"],
            "step": step,
            "progress": progress,
            **dict(data or {}),
        },
    )


def execute(config: dict[str, Any], request: dict[str, Any], result_path: Path) -> dict[str, Any]:
    request = validate_provisioning_request(request, expected_agent_id=str(config.get("agent_id") or ""))
    step = "accepted"
    materialized = False
    workspace: dict[str, str] | None = None
    content_result: dict[str, Any] | None = None
    compensation: list[str] = []
    _result(result_path, request, status="running", current_step=step, progress=5)
    _event("INSTANCE_PROVISIONING_STARTED", request, step=step, progress=5)
    try:
        step = "prepare_workspace"
        _result(result_path, request, status="running", current_step=step, progress=15)
        workspace = _prepare_workspace(request["instance_id"])
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=15)

        step = "validate_ports"
        _result(result_path, request, status="running", current_step=step, progress=25)
        ports = dict(request["ports"])
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=25, data={"port_roles": sorted(ports)})

        step = "install_content"
        _result(result_path, request, status="running", current_step=step, progress=35)
        content_command = {
            "action": request["content"]["action"],
            "selection": dict(request["content"]["selection"]),
        }
        content_result = execute_game_data(content_command)
        install_path = str(content_result["target_path"])
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=60, data={"provider": content_result.get("provider")})

        step = "build_runtime_spec"
        _result(result_path, request, status="running", current_step=step, progress=70)
        context = dict(request.get("configuration") or {})
        context["install_path"] = install_path
        context["content_root"] = install_path
        context["ports"] = ports
        instance = dict(request["instance"])
        spec = game_runtime.build_runtime_spec(config, instance, context)
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=75, data={"profile": spec.get("profile")})

        step = "materialize_runtime"
        _result(result_path, request, status="running", current_step=step, progress=82)
        materialization = privileged_materialization.materialize(config, spec)
        materialized = True
        _event("INSTANCE_PROVISIONING_STEP", request, step=step, progress=88, data={"adapter": spec.get("adapter")})

        step = "initial_reconcile"
        _result(result_path, request, status="running", current_step=step, progress=92)
        reconciliation = runtime_materialization.reconcile(config, request["instance_id"])
        observed_state = str(reconciliation.get("observed_state") or "unknown")
        final = _result(
            result_path,
            request,
            status="completed",
            current_step="completed",
            progress=100,
            desired_state=request["desired_state"],
            observed_state=observed_state,
            workspace=workspace,
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
                "materialized_changed": bool((materialization.get("operation") or {}).get("changed")),
            },
        )
        _event(
            "INSTANCE_PROVISIONING_COMPLETED",
            request,
            step="completed",
            progress=100,
            data={"desired_state": request["desired_state"], "observed_state": observed_state},
        )
        return final
    except Exception as exc:
        if materialized:
            try:
                privileged_materialization.remove(config, request["instance_id"])
                compensation.append("runtime_removed")
            except Exception:
                compensation.append("runtime_cleanup_failed")
        if workspace:
            staging = Path(workspace["staging"])
            try:
                shutil.rmtree(staging)
                staging.mkdir(parents=True, exist_ok=True)
                compensation.append("staging_cleaned")
            except OSError:
                compensation.append("staging_cleanup_failed")
        compensation.extend(["content_preserved_for_retry", "port_reservations_preserved"])
        failed = _result(
            result_path,
            request,
            status="failed",
            current_step=step,
            progress=100,
            error=str(exc)[:2000],
            compensation=compensation,
        )
        _event(
            "INSTANCE_PROVISIONING_FAILED",
            request,
            step=step,
            progress=100,
            data={"error": str(exc)[:2000], "compensation": compensation},
        )
        return failed


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: provisioning_executor.py CONFIG REQUEST RESULT", file=sys.stderr)
        return 2
    config_path = Path(sys.argv[1])
    request_path = Path(sys.argv[2])
    result_path = Path(sys.argv[3])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = execute(config, request, result_path)
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
