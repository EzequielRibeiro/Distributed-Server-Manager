#!/usr/bin/env python3
"""Consume instance-provisioning jobs for the local Agent in Hybrid mode."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from instance_provisioning_projection import project_agent_provisioning


def _state_root(root: Path) -> Path:
    return root / "runtime" / "hybrid-agent-state"


def _provision_root(root: Path) -> Path:
    return _state_root(root) / "instance-provisioning"


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > 191 or any(ch not in allowed for ch in text):
        raise ValueError("invalid provisioning_id")
    return text


def _paths(root: Path, provisioning_id: str) -> tuple[Path, Path, Path]:
    token = _safe_id(provisioning_id)
    base = _provision_root(root)
    return (
        base / f"{token}.request.json",
        base / f"{token}.result.json",
        base / f"{token}.log",
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def _latest_result(root: Path) -> dict[str, Any] | None:
    base = _provision_root(root)
    if not base.is_dir():
        return None
    items: list[tuple[float, dict[str, Any]]] = []
    for path in base.glob("*.result.json"):
        value = _read_json(path)
        if not value:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        items.append((modified, value))
    if not items:
        return None
    items.sort(key=lambda item: item[0], reverse=True)
    return items[0][1]


def _archive_final(root: Path, result: dict[str, Any]) -> None:
    status = str(result.get("status") or "").lower()
    if status not in {"completed", "failed"}:
        return
    provisioning_id = str(result.get("provisioning_id") or "").strip()
    if not provisioning_id:
        return
    request_path, result_path, log_path = _paths(root, provisioning_id)
    history = _provision_root(root) / "history"
    history.mkdir(parents=True, exist_ok=True)
    for source in (request_path, result_path, log_path):
        if not source.exists():
            continue
        destination = history / source.name
        try:
            os.replace(source, destination)
        except OSError:
            pass


def _provider_environment(root: Path) -> dict[str, str]:
    """Load non-secret provider runtime settings needed by local Hybrid execution."""
    allowed = {"DSM_STEAM_USER"}
    result: dict[str, str] = {}

    path = root / "config" / "providers" / "steam.conf"
    if not path.is_file():
        return result

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue

        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        if value:
            result[key] = value

    return result


def _runtime_config(root: Path, agent_id: str) -> tuple[Path, dict[str, Any]]:
    state_root = _state_root(root)
    storage_root = root / "runtime" / "hybrid-instance-storage"
    state_root.mkdir(parents=True, exist_ok=True)
    storage_root.mkdir(parents=True, exist_ok=True)
    config = {
        "agent_id": str(agent_id),
        "instance_storage_root": str(storage_root),
        "heartbeat_interval_seconds": 30,
        "degraded_after_seconds": 60,
        "offline_after_seconds": 120,
    }
    config_path = state_root / "agent.json"
    _write_json(config_path, config)
    return config_path, config


def _stage(root: Path, agent_id: str, command: dict[str, Any]) -> bool:
    provisioning_id = str(command.get("provisioning_id") or "").strip()
    instance_id = str(command.get("instance_id") or "").strip()
    if not provisioning_id or not instance_id:
        raise ValueError("invalid hybrid provisioning command")

    request_path, result_path, log_path = _paths(root, provisioning_id)
    existing = _read_json(result_path)
    if existing and str(existing.get("provisioning_id") or "") == provisioning_id:
        if str(existing.get("status") or "").lower() in {"running", "completed", "failed"}:
            return False

    config_path, _ = _runtime_config(root, agent_id)
    _write_json(request_path, command)
    _write_json(
        result_path,
        {
            "provisioning_id": provisioning_id,
            "instance_id": instance_id,
            "status": "running",
            "current_step": "staged",
            "progress": 1,
        },
    )

    executor = root / "agents" / "linux" / "runtime" / "provisioning_executor.py"
    if not executor.is_file():
        raise RuntimeError(f"hybrid provisioning executor not found: {executor}")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "ab", buffering=0)
    environment = {
        **os.environ,
        **_provider_environment(root),
        "DSM_ROOT": str(root),
        "CAPIVARA_AGENT_ROOT": str(root / "agents" / "linux"),
        "CAPIVARA_AGENT_STATE_DIR": str(_state_root(root)),
        "CAPIVARA_AGENT_CONFIG": str(config_path),
        "CAPIVARA_INSTANCE_WORKSPACE_ROOT": str(_state_root(root) / "instance-workspaces"),
        "CAPIVARA_MATERIALIZER_UNIT_TEMPLATE": "dsm-hybrid-agent-materialize@{instance_id}.service",
    }
    runtime_dir = root / "agents" / "linux" / "runtime"
    python_path = [str(runtime_dir), str(root), str(root / "database"), str(root / "dashboard")]
    if environment.get("PYTHONPATH"):
        python_path.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path)

    try:
        subprocess.Popen(
            [sys.executable, str(executor), str(config_path), str(request_path), str(result_path)],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
            env=environment,
        )
    except Exception as exc:
        _write_json(
            result_path,
            {
                "provisioning_id": provisioning_id,
                "instance_id": instance_id,
                "status": "failed",
                "current_step": "stage",
                "progress": 100,
                "error": str(exc)[:2000],
            },
        )
        raise
    finally:
        log_handle.close()
    return True


def process_hybrid_instance_provisioning_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    repository = AgentInstanceProvisioningRepository(backend)
    repository.initialize()

    reported = _latest_result(root)
    state = repository.apply_result(agent_id, reported) if reported else None
    if state:
        try:
            project_agent_provisioning(backend, state, root=root)
        except Exception:
            pass
    if reported and str(reported.get("status") or "").lower() in {"completed", "failed"}:
        _archive_final(root, reported)

    command = repository.command_for_agent(agent_id)
    staged = False
    if command:
        try:
            staged = _stage(root, agent_id, command)
        except Exception:
            # A failed staging result is persisted locally and will be reported on
            # the next cycle; do not leave a silently delivered command behind.
            staged = False
        if staged:
            state = repository.mark_delivered(str(command["provisioning_id"]))
            try:
                project_agent_provisioning(backend, state, root=root)
            except Exception:
                pass

    return {
        "state": state or {"status": "idle"},
        "command": command,
        "staged": staged,
    }


__all__ = ["process_hybrid_instance_provisioning_cycle"]
