#!/usr/bin/env python3
"""Persistent local Hybrid Agent inventory/heartbeat worker."""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[2])).resolve()
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from hybrid_game_data_client import process_hybrid_game_data_cycle
from hybrid_instance_provisioning_client import process_hybrid_instance_provisioning_cycle
from hybrid_local_reconciliation import reconcile_local_hybrid_runtime
from instance_workspace_repository import InstanceWorkspaceRepository
from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment

INTERVAL_SECONDS = max(10, int(os.environ.get("DSM_HYBRID_HEARTBEAT_SECONDS", "30")))
_ALLOWED_DB_KEYS = {
    "DSM_DATABASE_DRIVER",
    "DSM_DATABASE",
    "DSM_DATABASE_HOST",
    "DSM_DATABASE_PORT",
    "DSM_DATABASE_NAME",
    "DSM_DATABASE_USER",
    "DSM_DATABASE_PASSWORD_FILE",
    "DSM_DATABASE_TLS",
}


def _read_shell_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    pattern = re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        result[match.group(1)] = next((v for v in match.groups()[1:] if v is not None), "")
    return result


def _database_environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for key, value in _read_shell_values(root / "config" / "dsm.conf").items():
        if key in _ALLOWED_DB_KEYS and key not in environment:
            environment[key] = value
    environment.setdefault("DSM_ROOT", str(root))
    return environment


def _hybrid_agent_config(root: Path, agent_id: str) -> dict[str, Any]:
    path = root / "runtime" / "hybrid-agent-state" / "agent.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Hybrid Agent config is unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Hybrid Agent config must be a JSON object")
    configured = str(value.get("agent_id") or "").strip()
    if configured != agent_id:
        raise RuntimeError("Hybrid Agent config identity does not match agent.conf")
    return value


def _instance_runtime_module(root: Path):
    state = root / "runtime" / "hybrid-agent-state"
    os.environ.setdefault("CAPIVARA_AGENT_ROOT", str(root / "agents" / "linux"))
    os.environ.setdefault("CAPIVARA_AGENT_STATE_DIR", str(state))
    os.environ.setdefault("CAPIVARA_AGENT_CONFIG", str(state / "agent.json"))
    runtime = root / "agents" / "linux" / "runtime"
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    import instance_runtime
    return instance_runtime


def _instance_telemetry_module(root: Path):
    _instance_runtime_module(root)
    import instance_telemetry
    return instance_telemetry


def process_hybrid_instance_runtime_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    """Consume one Controller runtime command using the embedded Hybrid runtime."""
    repository = AgentInstanceRuntimeRepository(backend)
    command = repository.command_for_agent(agent_id)
    if not isinstance(command, dict):
        return {"status": "idle"}

    command_id = str(command.get("command_id") or "").strip()
    if not command_id:
        raise RuntimeError("Hybrid instance command is missing command_id")

    repository.mark_delivered(command_id)
    runtime = _instance_runtime_module(root)
    report = runtime.handle_command(_hybrid_agent_config(root, agent_id), command)
    completed = repository.apply_result(agent_id, report)
    if isinstance(completed, dict) and str(completed.get("status") or "").lower() in {"completed", "failed"}:
        runtime.clear_result(command_id)
    return {
        "status": str((completed or {}).get("status") or report.get("status") or "unknown"),
        "command_id": command_id,
        "instance_id": command.get("instance_id"),
        "action": command.get("action"),
    }


def process_hybrid_instance_telemetry_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    """Collect and persist telemetry for instances owned by the embedded Hybrid Agent."""
    telemetry = _instance_telemetry_module(root)
    config = _hybrid_agent_config(root, agent_id)
    samples = telemetry.collect_instance_telemetry(config)
    if not isinstance(samples, list):
        raise RuntimeError("Hybrid instance telemetry collector returned an invalid payload")

    repository = InstanceWorkspaceRepository(backend)
    repository.initialize()
    accepted = 0
    rejected = 0
    for sample in samples[:500]:
        if not isinstance(sample, dict):
            rejected += 1
            continue
        instance_id = str(sample.get("instance_id") or "").strip()
        if not instance_id:
            rejected += 1
            continue
        try:
            context = repository.instance_context(instance_id)
            if str(context.get("agent_id") or "") != agent_id:
                rejected += 1
                continue
            repository.record_telemetry(instance_id, sample)
            accepted += 1
        except (KeyError, ValueError, PermissionError):
            rejected += 1
    return {
        "status": "completed",
        "samples": len(samples),
        "accepted": accepted,
        "rejected": rejected,
    }


def heartbeat_cycle(root: Path = ROOT, *, backend=None) -> dict[str, Any]:
    config = _read_shell_values(root / "config" / "agent.conf")
    if str(config.get("DSM_NODE_ROLE", "")).strip().lower() != "hybrid":
        return {"active": False, "reason": "not_hybrid"}

    node_id = str(config.get("DSM_NODE_ID", "")).strip()
    agent_id = str(config.get("AGENT_ID", "")).strip()
    if not node_id or not agent_id:
        return {"active": False, "reason": "identity_incomplete"}

    effective_backend = backend or backend_from_environment(_database_environment(root))
    result = reconcile_local_hybrid_runtime(
        RegistryRepository(effective_backend),
        root,
        node_id=node_id,
        agent_id=agent_id,
        hostname=socket.gethostname(),
    )
    instance_runtime = process_hybrid_instance_runtime_cycle(effective_backend, root, agent_id)
    instance_telemetry = process_hybrid_instance_telemetry_cycle(effective_backend, root, agent_id)
    provisioning = process_hybrid_instance_provisioning_cycle(effective_backend, root, agent_id)
    game_data = process_hybrid_game_data_cycle(effective_backend, root, agent_id)
    return {
        "active": True,
        "agent_id": agent_id,
        "instance_runtime": instance_runtime,
        "instance_telemetry": instance_telemetry,
        "provisioning": provisioning,
        "game_data": game_data,
        **result,
    }


def run_forever(root: Path = ROOT) -> None:
    while True:
        try:
            result = heartbeat_cycle(root)
            if result.get("active"):
                game_data = result.get("game_data") if isinstance(result.get("game_data"), dict) else {}
                state = game_data.get("state") if isinstance(game_data.get("state"), dict) else {}
                instance_runtime = result.get("instance_runtime") if isinstance(result.get("instance_runtime"), dict) else {}
                instance_telemetry = result.get("instance_telemetry") if isinstance(result.get("instance_telemetry"), dict) else {}
                print(
                    f"hybrid heartbeat ok agent={result.get('agent_id')} health={result.get('health_status')} "
                    f"instance_runtime={instance_runtime.get('status', 'idle')} "
                    f"instance_telemetry={instance_telemetry.get('accepted', 0)} "
                    f"game_data={state.get('status', 'idle')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"hybrid heartbeat failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL_SECONDS)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "once":
        result = heartbeat_cycle(ROOT)
        print(result)
        return 0
    run_forever(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())