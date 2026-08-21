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
from game_data_client import clear_game_data_result, read_game_data_result, stage_game_data_command
from instance_runtime import clear_result as clear_instance_result
from instance_runtime import handle_command as handle_instance_command
from instance_runtime import inventory as instance_inventory
from instance_runtime import read_result as read_instance_result
from network_inventory import collect_network_inventory
from update_client import clear_update_result, read_update_result, stage_update_request

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
DEFAULT_HEARTBEAT_SECONDS = 30


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


def _inventory(config: dict[str, Any]) -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    version_path = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        installed_version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        installed_version = str(config.get("capivara_version", "unknown"))
    payload = {
        "agent_id": config["agent_id"],
        "hostname": socket.gethostname(),
        "os": platform.system().lower(),
        "architecture": platform.machine(),
        "capivara_version": installed_version,
        "address": config.get("advertise_address"),
        "fingerprint": config["fingerprint"],
        "capabilities": detect_capabilities(),
        "cpu": {"logical_cores": os.cpu_count(), "machine": platform.machine()},
        "ram_total_bytes": _memory_total_bytes(),
        "storage": {"root_total_bytes": disk.total, "root_free_bytes": disk.free},
        "network": collect_network_inventory(),
        "instances": instance_inventory(config),
        "heartbeat_interval_seconds": int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)),
        "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(config.get("offline_after_seconds", 120)),
    }
    update_result = read_update_result()
    if update_result:
        payload["update_result"] = update_result
    game_data_result = read_game_data_result()
    if game_data_result:
        payload["game_data_result"] = game_data_result
    instance_result = read_instance_result()
    if instance_result:
        payload["instance_result"] = instance_result
    return payload


def enroll(config: dict[str, Any]) -> dict[str, Any]:
    token = str(config.get("pairing_token", "")).strip()
    if not token:
        raise RuntimeError("Agent has no permanent credential and no pairing token")
    base = str(config["controller_url"]).rstrip("/")
    result = _post(
        base + "/api/agent/enroll",
        {
            "pairing_token": token,
            "agent_id": config["agent_id"],
            "node_id": config["node_id"],
            "name": config.get("name") or socket.gethostname(),
            "fingerprint": config["fingerprint"],
            "hostname": socket.gethostname(),
            "os": platform.system().lower(),
            "architecture": platform.machine(),
            "capivara_version": config.get("capivara_version"),
            "address": config.get("advertise_address"),
        },
    )
    config["controller_id"] = result["controller_id"]
    config["credential_id"] = result["credential_id"]
    config["credential_secret"] = result["credential_secret"]
    config["credential_type"] = result.get("credential_type", "opaque-v1")
    config.pop("pairing_token", None)
    _write_config(config)
    return config


def heartbeat(config: dict[str, Any]) -> dict[str, Any]:
    base = str(config["controller_url"]).rstrip("/")
    result = _post(
        base + "/api/agent/heartbeat",
        _inventory(config),
        headers={
            "X-Capivara-Agent-Credential": str(config["credential_id"]),
            "X-Capivara-Agent-Secret": str(config["credential_secret"]),
            "X-Capivara-Agent-Fingerprint": str(config["fingerprint"]),
        },
    )
    if result.get("update") and stage_update_request(dict(result["update"])):
        print(
            f"update staged version={result['update'].get('desired_version')} rollout={result['update'].get('rollout_id')}",
            flush=True,
        )
    if result.get("update_state", {}).get("update_status") == "completed":
        clear_update_result()
    command = result.get("game_data_command")
    if isinstance(command, dict) and stage_game_data_command(command):
        print(
            f"game-data staged job={command.get('job_id')} environment={command.get('environment_id')}",
            flush=True,
        )
    state = result.get("game_data_state") if isinstance(result.get("game_data_state"), dict) else {}
    if str(state.get("status") or "").lower() in {"completed", "failed"} and state.get("job_id"):
        clear_game_data_result(str(state["job_id"]))

    instance_command = result.get("instance_command")
    if isinstance(instance_command, dict):
        instance_result = handle_instance_command(config, instance_command)
        print(
            f"instance command action={instance_result.get('action')} instance={instance_result.get('instance_id')} status={instance_result.get('status')}",
            flush=True,
        )
    instance_state = result.get("instance_state") if isinstance(result.get("instance_state"), dict) else {}
    if str(instance_state.get("status") or "").lower() in {"completed", "failed"} and instance_state.get("command_id"):
        clear_instance_result(str(instance_state["command_id"]))
    return result


def run_forever() -> None:
    config = _load_config()
    if not config.get("credential_id") or not config.get("credential_secret"):
        config = enroll(config)
    interval = max(10, int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)))
    while True:
        try:
            result = heartbeat(config)
            print(
                f"heartbeat ok agent={result.get('agent_id')} health={result.get('health_status')} status={result.get('status')}",
                flush=True,
            )
        except Exception as exc:
            print(f"heartbeat failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
