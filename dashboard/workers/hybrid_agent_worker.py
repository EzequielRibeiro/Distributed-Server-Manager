#!/usr/bin/env python3
"""Persistent local Hybrid Agent inventory/heartbeat worker."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
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
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from backup_repository import BackupRepository
from configuration_repository import ConfigurationRepository
from content_repository import ContentRepository
from hybrid_game_data_client import process_hybrid_game_data_cycle
from hybrid_instance_provisioning_client import process_hybrid_instance_provisioning_cycle
from hybrid_local_reconciliation import reconcile_local_hybrid_runtime
from instance_workspace_repository import InstanceWorkspaceRepository
from observability_repository import ObservabilityRepository
from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment

INTERVAL_SECONDS = max(10, int(os.environ.get("DSM_HYBRID_HEARTBEAT_SECONDS", "30")))
HYBRID_AGENT_LOG_MAX_BYTES = 262144
HYBRID_AGENT_LOG_MAX_LINES = 200
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
_SAFE_INSTANCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,191}$")


def _hybrid_agent_log_path(root: Path) -> Path:
    return root / "runtime" / "hybrid-agent-state" / "agent-runtime.log"


def _append_hybrid_agent_log(root: Path, message: str, *, error: bool = False) -> str:
    line = (
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
        f"{'ERROR' if error else 'INFO'} {message}"
    )
    path = _hybrid_agent_log_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > HYBRID_AGENT_LOG_MAX_BYTES:
            path.replace(path.with_suffix(".log.1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    return line


def _recent_hybrid_agent_logs(root: Path, limit: int = HYBRID_AGENT_LOG_MAX_LINES) -> list[str]:
    try:
        return _hybrid_agent_log_path(root).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()[-limit:]
    except OSError:
        return []


def _publish_hybrid_agent_logs(backend, root: Path, agent_id: str) -> int:
    from agent_heartbeat_api import _store_agent_metadata

    logs = _recent_hybrid_agent_logs(root)
    if not logs:
        return 0
    _store_agent_metadata(agent_id, {"agent_logs": logs}, backend=backend)
    return len(logs)


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


def _hybrid_agent_config(
    root: Path,
    agent_id: str,
    *,
    optional: bool = False,
) -> dict[str, Any] | None:
    path = root / "runtime" / "hybrid-agent-state" / "agent.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if optional:
            return None
        raise RuntimeError(f"Hybrid Agent config is unavailable: {exc}") from exc
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
    os.environ.setdefault(
        "CAPIVARA_MATERIALIZER_UNIT_TEMPLATE",
        "dsm-hybrid-agent-materialize@{instance_id}.service",
    )
    runtime = root / "agents" / "linux" / "runtime"
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    import instance_runtime
    return instance_runtime


def _runtime_reconciler_module(root: Path):
    _instance_runtime_module(root)
    import runtime_reconciler
    return runtime_reconciler


def _instance_telemetry_module(root: Path):
    _instance_runtime_module(root)
    import instance_telemetry
    return instance_telemetry


def _runtime_health_module(root: Path):
    _instance_runtime_module(root)
    import runtime_health
    return runtime_health


def _backup_client_module(root: Path):
    _instance_runtime_module(root)
    import backup_client
    return backup_client


def _configuration_client_module(root: Path):
    _instance_runtime_module(root)
    import configuration_client
    return configuration_client


def _content_client_module(root: Path):
    _instance_runtime_module(root)
    import content_client
    return content_client


def _prepare_hybrid_customer_files_access(instance_id: str) -> None:
    if not _SAFE_INSTANCE_ID.fullmatch(instance_id):
        raise ValueError("invalid instance_id for Hybrid files access helper")
    template = os.environ.get(
        "CAPIVARA_HYBRID_FILES_ACCESS_UNIT_TEMPLATE",
        "dsm-hybrid-agent-files-access@{instance_id}.service",
    )
    unit = template.format(instance_id=instance_id)
    subprocess.run(
        ["systemctl", "start", unit, "--no-pager"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def process_hybrid_instance_reconcile_cycle(root: Path, agent_id: str) -> dict[str, Any]:
    """Reconcile embedded Hybrid runtimes and repair customer-manageable file access."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {
            "status": "unavailable",
            "reason": "config_unavailable",
            "instances": 0,
            "healthy": 0,
            "files_access_prepared": 0,
            "files_access_failed": 0,
        }

    reconciler = _runtime_reconciler_module(root)
    results = reconciler.reconcile_all(config)
    if not isinstance(results, list):
        raise RuntimeError("Hybrid runtime reconciler returned an invalid payload")

    healthy = 0
    prepared = 0
    access_failed = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        if str(result.get("status") or "").lower() == "healthy":
            healthy += 1
        instance_id = str(result.get("instance_id") or "").strip()
        if not instance_id:
            continue
        try:
            _prepare_hybrid_customer_files_access(instance_id)
            prepared += 1
        except (OSError, ValueError, subprocess.SubprocessError):
            access_failed += 1

    return {
        "status": "completed",
        "instances": len(results),
        "healthy": healthy,
        "files_access_prepared": prepared,
        "files_access_failed": access_failed,
    }


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


def _ingest_hybrid_instance_observability(backend, agent_id: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Project accepted Hybrid instance samples into the shared observability timeline."""
    from agent_heartbeat_api import _observability_from_heartbeat

    metrics = _observability_from_heartbeat(agent_id, {"instance_telemetry": samples})
    repository = ObservabilityRepository(backend)
    repository.initialize()
    return repository.ingest_agent_samples(agent_id, metrics)


def process_hybrid_instance_telemetry_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    """Collect and persist telemetry for instances owned by the embedded Hybrid Agent."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {
            "status": "unavailable",
            "reason": "config_unavailable",
            "samples": 0,
            "accepted": 0,
            "rejected": 0,
        }

    telemetry = _instance_telemetry_module(root)
    samples = telemetry.collect_instance_telemetry(config)
    if not isinstance(samples, list):
        raise RuntimeError("Hybrid instance telemetry collector returned an invalid payload")

    repository = InstanceWorkspaceRepository(backend)
    repository.initialize()
    accepted = 0
    rejected = 0
    accepted_samples: list[dict[str, Any]] = []
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
            accepted_samples.append(dict(sample))
        except (KeyError, ValueError, PermissionError):
            rejected += 1

    _ingest_hybrid_instance_observability(backend, agent_id, accepted_samples)
    return {
        "status": "completed",
        "samples": len(samples),
        "accepted": accepted,
        "rejected": rejected,
    }


def process_hybrid_instance_health_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    """Persist embedded Hybrid instance runtime health in Controller state."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {
            "status": "unavailable",
            "reason": "config_unavailable",
            "samples": 0,
            "applied": 0,
            "healthy": 0,
            "degraded": 0,
            "unknown": 0,
        }

    runtime_health = _runtime_health_module(root)
    inventory = runtime_health.health_inventory(config)

    if not isinstance(inventory, list):
        raise RuntimeError(
            "Hybrid runtime health collector returned an invalid payload"
        )

    inventory = [
        dict(item)
        for item in inventory[:1000]
        if isinstance(item, dict)
    ]

    repository = AgentInstanceRuntimeHealthRepository(backend)
    repository.initialize()
    applied = repository.apply_inventory(agent_id, inventory)

    if not isinstance(applied, list):
        raise RuntimeError(
            "Hybrid runtime health repository returned an invalid result"
        )

    return {
        "status": "completed",
        "samples": len(inventory),
        "applied": len(applied),
        "healthy": sum(
            1
            for item in applied
            if str(item.get("health") or "").lower() == "healthy"
        ),
        "degraded": sum(
            1
            for item in applied
            if str(item.get("health") or "").lower() == "degraded"
        ),
        "unknown": sum(
            1
            for item in applied
            if str(item.get("health") or "").lower() == "unknown"
        ),
    }


def process_hybrid_configuration_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    """Round-trip Controller desired configuration through the embedded Hybrid Agent."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {
            "status": "unavailable",
            "reason": "config_unavailable",
            "reported": 0,
            "commands": 0,
            "accepted": 0,
            "applied": 0,
            "failed": 0,
        }

    client = _configuration_client_module(root)
    repository = ConfigurationRepository(backend)
    repository.initialize()

    previous = client.configuration_state()
    if not isinstance(previous, list):
        raise RuntimeError("Hybrid configuration client returned an invalid state payload")
    previous = [item for item in previous if isinstance(item, dict)]
    reported = repository.record_agent_state(agent_id, previous)

    commands = repository.desired_for_agent(agent_id)
    if not isinstance(commands, list):
        raise RuntimeError("Hybrid configuration repository returned an invalid command payload")
    commands = [item for item in commands if isinstance(item, dict)]

    reports = client.apply_configuration_commands(commands)
    if not isinstance(reports, list):
        raise RuntimeError("Hybrid configuration client returned an invalid result payload")
    reports = [item for item in reports if isinstance(item, dict)]
    accepted = repository.record_agent_state(agent_id, reports)

    return {
        "status": "completed",
        "reported": reported,
        "commands": len(commands),
        "accepted": accepted,
        "applied": sum(
            1 for item in reports
            if str(item.get("status") or "").lower() == "applied"
        ),
        "failed": sum(
            1 for item in reports
            if str(item.get("status") or "").lower() == "failed"
        ),
    }


def process_hybrid_content_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    """Round-trip Universal Content desired state through the embedded Hybrid Agent."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {
            "status": "unavailable",
            "reason": "config_unavailable",
            "reported": 0,
            "commands": 0,
            "accepted": 0,
            "applied": 0,
            "failed": 0,
        }

    client = _content_client_module(root)
    repository = ContentRepository(backend)
    repository.initialize()

    previous = client.content_state()
    if not isinstance(previous, list):
        raise RuntimeError("Hybrid content client returned an invalid state payload")
    previous = [item for item in previous if isinstance(item, dict)]
    reported = repository.record_agent_state(agent_id, previous)

    commands = repository.desired_for_agent(agent_id)
    if not isinstance(commands, list):
        raise RuntimeError("Hybrid content repository returned an invalid command payload")
    commands = [item for item in commands if isinstance(item, dict)]

    reports = client.apply_content_commands(config, commands)
    if not isinstance(reports, list):
        raise RuntimeError("Hybrid content client returned an invalid result payload")
    reports = [item for item in reports if isinstance(item, dict)]
    accepted = repository.record_agent_state(agent_id, reports)

    return {
        "status": "completed",
        "reported": reported,
        "commands": len(commands),
        "accepted": accepted,
        "applied": sum(
            1 for item in reports
            if str(item.get("status") or "").lower() == "applied"
        ),
        "failed": sum(
            1 for item in reports
            if str(item.get("status") or "").lower()
            in {"failed", "security_scan_failed", "security_blocked", "rollback_failed"}
        ),
    }


def process_hybrid_backup_cycle(
    backend,
    root: Path,
    agent_id: str,
) -> dict[str, Any]:
    """Round-trip Universal Smart Backup commands for the embedded Hybrid Agent."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {
            "status": "unavailable",
            "reason": "config_unavailable",
            "reported": 0,
            "commands": 0,
            "accepted": 0,
            "completed": 0,
            "failed": 0,
        }

    client = _backup_client_module(root)
    repository = BackupRepository(backend)
    repository.initialize()

    previous = client.backup_state()
    if not isinstance(previous, list):
        raise RuntimeError("Hybrid backup client returned an invalid state payload")
    previous = [item for item in previous if isinstance(item, dict)]
    reported = repository.record_agent_state(agent_id, previous)

    commands = repository.commands_for_agent(agent_id)
    if not isinstance(commands, list):
        raise RuntimeError("Hybrid backup repository returned an invalid command payload")
    commands = [item for item in commands if isinstance(item, dict)]

    reports = client.apply_backup_commands(config, commands)
    if not isinstance(reports, list):
        raise RuntimeError("Hybrid backup client returned an invalid result payload")
    reports = [item for item in reports if isinstance(item, dict)]

    accepted = repository.record_agent_state(agent_id, reports)

    return {
        "status": "completed",
        "reported": reported,
        "commands": len(commands),
        "accepted": accepted,
        "completed": sum(
            1 for item in reports
            if str(item.get("status") or "").lower() == "completed"
        ),
        "failed": sum(
            1 for item in reports
            if str(item.get("status") or "").lower() == "failed"
        ),
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
    instance_reconcile = process_hybrid_instance_reconcile_cycle(root, agent_id)
    configuration = process_hybrid_configuration_cycle(effective_backend, root, agent_id)
    content = process_hybrid_content_cycle(effective_backend, root, agent_id)
    instance_runtime = process_hybrid_instance_runtime_cycle(effective_backend, root, agent_id)
    instance_telemetry = process_hybrid_instance_telemetry_cycle(effective_backend, root, agent_id)
    instance_health = process_hybrid_instance_health_cycle(effective_backend, root, agent_id)
    backup = process_hybrid_backup_cycle(effective_backend, root, agent_id)
    provisioning = process_hybrid_instance_provisioning_cycle(effective_backend, root, agent_id)
    game_data = process_hybrid_game_data_cycle(effective_backend, root, agent_id)
    response = {
        "active": True,
        "agent_id": agent_id,
        "instance_reconcile": instance_reconcile,
        "configuration": configuration,
        "content": content,
        "instance_runtime": instance_runtime,
        "instance_telemetry": instance_telemetry,
        "instance_health": instance_health,
        "backup": backup,
        "provisioning": provisioning,
        "game_data": game_data,
        **result,
    }
    game_state = game_data.get("state") if isinstance(game_data.get("state"), dict) else {}
    message = (
        f"hybrid heartbeat ok agent={agent_id} health={response.get('health_status')} "
        f"instance_reconcile={instance_reconcile.get('healthy', 0)}/{instance_reconcile.get('instances', 0)} "
        f"instance_files={instance_reconcile.get('files_access_prepared', 0)} "
        f"configuration={configuration.get('applied', 0)}a/{configuration.get('failed', 0)}f "
        f"content={content.get('applied', 0)}a/{content.get('failed', 0)}f "
        f"instance_runtime={instance_runtime.get('status', 'idle')} "
        f"instance_telemetry={instance_telemetry.get('accepted', 0)} "
        f"instance_health={instance_health.get('healthy', 0)}/{instance_health.get('applied', 0)} "
        f"backup={backup.get('completed', 0)}c/{backup.get('failed', 0)}f "
        f"game_data={game_state.get('status', 'idle')}"
    )
    _append_hybrid_agent_log(root, message)
    try:
        response["published_log_lines"] = _publish_hybrid_agent_logs(
            effective_backend, root, agent_id
        )
    except Exception:
        response["published_log_lines"] = 0
    response["log_message"] = message
    return response


def run_forever(root: Path = ROOT) -> None:
    while True:
        try:
            result = heartbeat_cycle(root)
            if result.get("active"):
                print(result.get("log_message") or "hybrid heartbeat ok", flush=True)
        except Exception as exc:
            message = f"hybrid heartbeat failed: {exc}"
            _append_hybrid_agent_log(root, message, error=True)
            print(message, file=sys.stderr, flush=True)
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
