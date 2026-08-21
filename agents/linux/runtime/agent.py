#!/usr/bin/env python3
"""Capivara Linux Agent runtime: enroll once, then heartbeat permanently."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from capabilities import detect_capabilities
from configuration_client import apply_configuration_commands, configuration_state
from game_data_client import clear_game_data_result, read_game_data_result, stage_game_data_command
from instance_runtime import clear_result as clear_instance_result
from instance_runtime import handle_command as handle_instance_command
from instance_runtime import inventory as instance_inventory
from instance_runtime import read_result as read_instance_result
from network_inventory import collect_network_inventory
from provisioning_client import clear_provisioning_result, read_provisioning_result, stage_provisioning_command
from runtime_events import acknowledge_runtime_events, read_runtime_events
from runtime_health import health_inventory
from runtime_metrics import increment, snapshot as runtime_metrics_snapshot
from runtime_operations import recover_interrupted_operations
from runtime_reconciler import reconcile_all, reconciliation_inventory
from update_client import clear_update_result, read_update_result, stage_update_request

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
DEFAULT_HEARTBEAT_SECONDS = 30
DEFAULT_RECONCILE_SECONDS = 15


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _write_config(config: dict[str, Any]) -> None:
    temp = CONFIG_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)


def _post(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Controller rejected request ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc


def _memory_total_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _queue_depth() -> dict[str, int]:
    def count(pattern: str) -> int:
        try:
            return sum(1 for _ in Path(pattern).parent.glob(Path(pattern).name))
        except OSError:
            return 0
    state = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
    return {
        "instance_results": count(str(state / "instance-results" / "*.json")),
        "provisioning": count(str(state / "instance-provisioning" / "*.request.json")),
        "game_data": count(str(state / "game-data-jobs" / "*.json")),
        "runtime_events": len(read_runtime_events(state, limit=1000)),
    }


def _inventory(config: dict[str, Any]) -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    version_path = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        installed_version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        installed_version = str(config.get("capivara_version", "unknown"))
    state = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
    payload = {
        "agent_id": config["agent_id"], "hostname": socket.gethostname(), "os": platform.system().lower(),
        "architecture": platform.machine(), "capivara_version": installed_version,
        "address": config.get("advertise_address"), "fingerprint": config["fingerprint"],
        "capabilities": detect_capabilities(), "cpu": {"logical_cores": os.cpu_count(), "machine": platform.machine()},
        "ram_total_bytes": _memory_total_bytes(), "storage": {"root_total_bytes": disk.total, "root_free_bytes": disk.free},
        "network": collect_network_inventory(), "instances": instance_inventory(config),
        "instance_reconciliation": reconciliation_inventory(config), "instance_runtime_health": health_inventory(config),
        "instance_runtime_metrics": runtime_metrics_snapshot(queue_depth=_queue_depth()),
        "runtime_events": read_runtime_events(state, limit=int(config.get("event_batch_size", 200))),
        "configuration_state": configuration_state(),
        "heartbeat_interval_seconds": int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)),
        "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(config.get("offline_after_seconds", 120)),
    }
    update_result = read_update_result()
    if update_result: payload["update_result"] = update_result
    provisioning_result = read_provisioning_result()
    if provisioning_result: payload["provisioning_result"] = provisioning_result
    game_data_result = read_game_data_result()
    if game_data_result: payload["game_data_result"] = game_data_result
    instance_result = read_instance_result()
    if instance_result: payload["instance_result"] = instance_result
    return payload


def enroll(config: dict[str, Any]) -> dict[str, Any]:
    token = str(config.get("pairing_token", "")).strip()
    if not token: raise RuntimeError("Agent has no permanent credential and no pairing token")
    base = str(config["controller_url"]).rstrip("/")
    result = _post(base + "/api/agent/enroll", {
        "pairing_token": token, "agent_id": config["agent_id"], "node_id": config["node_id"],
        "name": config.get("name") or socket.gethostname(), "fingerprint": config["fingerprint"],
        "hostname": socket.gethostname(), "os": platform.system().lower(), "architecture": platform.machine(),
        "capivara_version": config.get("capivara_version"), "address": config.get("advertise_address"),
    })
    config["controller_id"] = result["controller_id"]
    config["credential_id"] = result["credential_id"]
    config["credential_secret"] = result["credential_secret"]
    config["credential_type"] = result.get("credential_type", "opaque-v1")
    config.pop("pairing_token", None)
    _write_config(config)
    return config


def heartbeat(config: dict[str, Any]) -> dict[str, Any]:
    base = str(config["controller_url"]).rstrip("/")
    result = _post(base + "/api/agent/heartbeat", _inventory(config), headers={
        "X-Capivara-Agent-Credential": str(config["credential_id"]),
        "X-Capivara-Agent-Secret": str(config["credential_secret"]),
        "X-Capivara-Agent-Fingerprint": str(config["fingerprint"]),
    })
    accepted_event_ids = result.get("accepted_event_ids")
    if isinstance(accepted_event_ids, list):
        state_root = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
        acknowledge_runtime_events(state_root, accepted_event_ids)
    commands = result.get("configuration_commands")
    if isinstance(commands, list):
        applied = apply_configuration_commands([item for item in commands if isinstance(item, dict)])
        if applied:
            print(f"configuration applied reports={len(applied)}", flush=True)
    if result.get("update") and stage_update_request(dict(result["update"])):
        print(f"update staged version={result['update'].get('desired_version')} rollout={result['update'].get('rollout_id')}", flush=True)
    if result.get("update_state", {}).get("update_status") == "completed": clear_update_result()
    provisioning_command = result.get("provisioning_command")
    if isinstance(provisioning_command, dict) and stage_provisioning_command(provisioning_command, config_path=CONFIG_PATH):
        print(f"provisioning staged id={provisioning_command.get('provisioning_id')} instance={provisioning_command.get('instance_id')}", flush=True)
    provisioning_state = result.get("provisioning_state") if isinstance(result.get("provisioning_state"), dict) else {}
    if str(provisioning_state.get("status") or "").lower() in {"completed", "failed"} and provisioning_state.get("provisioning_id"):
        clear_provisioning_result(str(provisioning_state["provisioning_id"]))
    command = result.get("game_data_command")
    if isinstance(command, dict) and stage_game_data_command(command):
        print(f"game-data staged job={command.get('job_id')} environment={command.get('environment_id')}", flush=True)
    state = result.get("game_data_state") if isinstance(result.get("game_data_state"), dict) else {}
    if str(state.get("status") or "").lower() in {"completed", "failed"} and state.get("job_id"):
        clear_game_data_result(str(state["job_id"]))
    instance_command = result.get("instance_command")
    if isinstance(instance_command, dict):
        instance_result = handle_instance_command(config, instance_command)
        print(f"instance command action={instance_result.get('action')} instance={instance_result.get('instance_id')} status={instance_result.get('status')}", flush=True)
    instance_state = result.get("instance_state") if isinstance(result.get("instance_state"), dict) else {}
    if str(instance_state.get("status") or "").lower() in {"completed", "failed"} and instance_state.get("command_id"):
        clear_instance_result(str(instance_state["command_id"]))
    return result


def run_forever() -> None:
    config = _load_config()
    if not config.get("credential_id") or not config.get("credential_secret"): config = enroll(config)
    interrupted = recover_interrupted_operations(config)
    if interrupted: increment("operations_interrupted", len(interrupted))
    heartbeat_interval = max(10, int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)))
    reconcile_interval = max(5, int(config.get("reconcile_interval_seconds", DEFAULT_RECONCILE_SECONDS)))
    next_heartbeat = 0.0; next_reconcile = 0.0
    while True:
        now = time.monotonic()
        if now >= next_reconcile:
            try: reconcile_all(config)
            except Exception as exc: print(f"reconcile loop failed: {exc}", file=sys.stderr, flush=True)
            next_reconcile = now + reconcile_interval
        if now >= next_heartbeat:
            try:
                result = heartbeat(config)
                print(f"heartbeat ok agent={result.get('agent_id')} health={result.get('health_status')} status={result.get('status')}", flush=True)
            except Exception as exc: print(f"heartbeat failed: {exc}", file=sys.stderr, flush=True)
            next_heartbeat = now + heartbeat_interval
        sleep_for = max(0.25, min(next_reconcile, next_heartbeat) - time.monotonic())
        time.sleep(min(sleep_for, 1.0))


if __name__ == "__main__":
    run_forever()
