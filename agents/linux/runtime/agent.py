#!/usr/bin/env python3
"""Capivara DSM Linux Agent runtime worker."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from backup_client import backup_state
from broadcast_client import broadcast_state
from capabilities import detect_capabilities
from configuration_client import configuration_state
from console_client import console_state, read_result as read_console_result
from content_client import content_state
from game_data_client import read_game_data_result
from instance_runtime import inventory as instance_inventory
from instance_telemetry import collect_instance_telemetry
from network_inventory import collect_network_inventory
from runtime_events import read_runtime_events
from runtime_health import health_inventory
from runtime_metrics import snapshot as runtime_metrics_snapshot
from runtime_reconciler import reconciliation_inventory
from update_client import read_update_result

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
HOST_IDENTITY_PATH = Path(
    os.environ.get("CAPIVARA_AGENT_HOST_IDENTITY", str(STATE_DIR / "host-identity"))
)
DEFAULT_HEARTBEAT_SECONDS = 30


def _load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default


def _load_config():
    config = _load_json(CONFIG_PATH)
    if not isinstance(config, dict):
        raise RuntimeError("Agent configuration is invalid")
    required = (
        "agent_id",
        "node_id",
        "controller_id",
        "controller_url",
        "credential_id",
        "credential_secret",
        "fingerprint",
    )
    missing = [key for key in required if not str(config.get(key) or "").strip()]
    if missing:
        raise RuntimeError("Agent configuration is missing: " + ", ".join(missing))
    return config


def _json_request(url, *, payload=None, headers=None, timeout=30, ssl_context=None):
    body = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Controller rejected request ({exc.code}): {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip().lower()
    except OSError:
        return ""


def _host_identity():
    """Return the canonical, non-secret identity for the physical/virtual host."""
    canonical = _read_text(HOST_IDENTITY_PATH)
    if canonical:
        return canonical

    # Backward-compatible fallback for installations that have not yet run the
    # privileged host-identity materializer. New installs should always use the
    # canonical state file so identity does not depend on runtime privileges.
    machine_id = _read_text("/etc/machine-id")
    product_uuid = _read_text("/sys/class/dmi/id/product_uuid")

    macs = []
    try:
        interfaces = Path("/sys/class/net").iterdir()
    except OSError:
        interfaces = ()

    for interface in interfaces:
        if interface.name == "lo":
            continue
        value = _read_text(interface / "address")
        if value and value != "00:00:00:00:00:00":
            macs.append(value)

    hardware_identity = product_uuid or "|".join(sorted(set(macs)))
    components = [
        "capivara-host-v1",
        machine_id,
        hardware_identity,
    ]

    material = "\n".join(components).encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _memory_total_bytes():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _queue_depth():
    def count(pattern):
        return len(list(STATE_DIR.glob(pattern)))

    return {
        "game_data": count("game-data-jobs/*.json"),
        "backup_results": count("backup-results/*.json"),
        "broadcast_state": count("broadcast-state/*.json"),
        "runtime_events": len(read_runtime_events(STATE_DIR, limit=1000)),
    }


def _recent_logs():
    try:
        completed = subprocess.run(
            ["journalctl", "-u", "capivara-agent.service", "--no-pager", "-n", "50", "-o", "short-iso"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in completed.stdout.splitlines() if line][-50:]


def _inventory(config):
    disk = shutil.disk_usage("/")
    version_path = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        installed_version = version_path.read_text().strip()
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
        "host_identity": _host_identity(),
        "capabilities": detect_capabilities(),
        "cpu": {"logical_cores": os.cpu_count(), "machine": platform.machine()},
        "ram_total_bytes": _memory_total_bytes(),
        "storage": {"root_total_bytes": disk.total, "root_free_bytes": disk.free},
        "network": collect_network_inventory(),
        "instances": instance_inventory(config),
        "instance_reconciliation": reconciliation_inventory(config),
        "instance_runtime_health": health_inventory(config),
        "instance_telemetry": collect_instance_telemetry(config),
        "instance_console_state": console_state(config),
        "instance_runtime_metrics": runtime_metrics_snapshot(queue_depth=_queue_depth()),
        "runtime_events": read_runtime_events(STATE_DIR, limit=int(config.get("event_batch_size", 200))),
        "configuration_state": configuration_state(),
        "content_state": content_state(),
        "backup_state": backup_state(),
        "broadcast_state": broadcast_state(),
        "heartbeat_interval_seconds": int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)),
        "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(config.get("offline_after_seconds", 120)),
    }
    payload["agent_logs"] = _recent_logs()
    result_readers = (
        ("update_result", read_update_result),
        ("game_data_result", read_game_data_result),
        ("console_result", read_console_result),
    )
    for key, reader in result_readers:
        try:
            value = reader()
        except Exception:
            value = None
        if value is not None:
            payload[key] = value
    return payload


def _ssl_context(config):
    if not str(config.get("controller_url") or "").lower().startswith("https://"):
        return None
    ca_file = str(config.get("controller_ca_file") or "").strip()
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    return ssl.create_default_context()


def _heartbeat(config):
    controller = str(config["controller_url"]).rstrip("/")
    headers = {
        "X-Capivara-Agent-Credential": str(config["credential_id"]),
        "X-Capivara-Agent-Secret": str(config["credential_secret"]),
        "X-Capivara-Agent-Fingerprint": str(config["fingerprint"]),
    }
    return _json_request(
        controller + "/api/agent/heartbeat",
        payload=_inventory(config),
        headers=headers,
        timeout=int(config.get("controller_timeout_seconds", 30)),
        ssl_context=_ssl_context(config),
    )


def main():
    config = _load_config()
    interval = max(5, int(config.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_SECONDS)))

    while True:
        try:
            response = _heartbeat(config)
            health = str(response.get("health_status") or response.get("health") or "online")
            status = str(response.get("status") or "active")
            print(
                f"heartbeat ok agent={config['agent_id']} health={health} status={status}",
                flush=True,
            )
        except Exception as exc:
            print(f"heartbeat failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
