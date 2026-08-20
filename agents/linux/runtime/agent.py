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
    return {
        "agent_id": config["agent_id"],
        "hostname": socket.gethostname(),
        "os": platform.system().lower(),
        "architecture": platform.machine(),
        "capivara_version": str(config.get("capivara_version", "unknown")),
        "address": config.get("advertise_address"),
        "fingerprint": config["fingerprint"],
        "capabilities": {
            "runtime": "linux",
            "systemd": Path("/run/systemd/system").exists(),
            "game_server": True,
        },
        "cpu": {
            "logical_cores": os.cpu_count(),
            "machine": platform.machine(),
        },
        "ram_total_bytes": _memory_total_bytes(),
        "storage": {
            "root_total_bytes": disk.total,
            "root_free_bytes": disk.free,
        },
        "heartbeat_interval_seconds": int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)),
        "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(config.get("offline_after_seconds", 120)),
    }


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
    return _post(
        base + "/api/agent/heartbeat",
        _inventory(config),
        headers={
            "X-Capivara-Agent-Credential": str(config["credential_id"]),
            "X-Capivara-Agent-Secret": str(config["credential_secret"]),
            "X-Capivara-Agent-Fingerprint": str(config["fingerprint"]),
        },
    )


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
        except Exception as exc:  # systemd supervises retries; never discard identity.
            print(f"heartbeat failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
