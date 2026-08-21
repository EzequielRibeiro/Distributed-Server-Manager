#!/usr/bin/env python3
"""Local, read-only operational CLI for a standalone Linux Agent."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from capabilities import detect_capabilities
from network_inventory import collect_network_inventory

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
SERVICE_NAME = os.environ.get("CAPIVARA_AGENT_SERVICE", "capivara-agent.service")


def _read_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Agent config not found: {CONFIG_PATH}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Agent config is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Agent config must be a JSON object")
    return payload


def _installed_version(config: dict[str, Any]) -> str:
    for candidate in (INSTALL_ROOT / "VERSION", RUNTIME_DIR.parent / "VERSION"):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return str(config.get("capivara_version") or "unknown")


def _run(command: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    output = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, output


def _service_state() -> dict[str, Any]:
    code, output = _run(
        [
            "systemctl",
            "show",
            SERVICE_NAME,
            "--property=LoadState,ActiveState,SubState",
            "--value",
        ]
    )
    values = output.splitlines() if output else []
    load_state = values[0] if len(values) > 0 else "unknown"
    active_state = values[1] if len(values) > 1 else "unknown"
    sub_state = values[2] if len(values) > 2 else "unknown"
    return {
        "service": SERVICE_NAME,
        "available": code == 0 and load_state != "not-found",
        "load_state": load_state,
        "active_state": active_state,
        "sub_state": sub_state,
        "healthy": active_state == "active",
    }


def _controller_probe(config: dict[str, Any]) -> dict[str, Any]:
    base = str(config.get("controller_url") or "").strip().rstrip("/")
    if not base:
        return {"configured": False, "reachable": False, "error": "controller_url is missing"}
    request = urllib.request.Request(
        base + "/ping",
        headers={"Accept": "application/json", "User-Agent": "Capivara-Agent-CLI"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "configured": True,
                "reachable": 200 <= int(response.status) < 300,
                "status_code": int(response.status),
                "response": body[:500],
            }
    except urllib.error.HTTPError as exc:
        return {"configured": True, "reachable": False, "status_code": exc.code, "error": str(exc)}
    except (urllib.error.URLError, OSError) as exc:
        return {"configured": True, "reachable": False, "error": str(exc)}


def _memory_total_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _host() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    return {
        "hostname": socket.gethostname(),
        "os": platform.system().lower(),
        "architecture": platform.machine(),
        "cpu_logical_cores": os.cpu_count(),
        "ram_total_bytes": _memory_total_bytes(),
        "storage_root_total_bytes": disk.total,
        "storage_root_free_bytes": disk.free,
    }


def _identity(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": config.get("agent_id"),
        "node_id": config.get("node_id"),
        "name": config.get("name") or socket.gethostname(),
        "controller_id": config.get("controller_id"),
        "controller_url": config.get("controller_url"),
        "enrolled": bool(config.get("credential_id") and config.get("credential_secret")),
        "credential_type": config.get("credential_type"),
        "fingerprint": config.get("fingerprint"),
        "version": _installed_version(config),
    }


def _heartbeat(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "interval_seconds": int(config.get("heartbeat_interval_seconds", 30)),
        "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)),
        "offline_after_seconds": int(config.get("offline_after_seconds", 120)),
        "controller": _controller_probe(config),
    }


def _port_ranges(config: dict[str, Any]) -> list[dict[str, Any]]:
    ranges = config.get("port_ranges", [])
    if not isinstance(ranges, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in ranges:
        if not isinstance(item, dict):
            continue
        protocol = str(item.get("protocol", "")).lower()
        try:
            start = int(item.get("start_port"))
            end = int(item.get("end_port"))
        except (TypeError, ValueError):
            continue
        if protocol in {"tcp", "udp"} and 1 <= start <= end <= 65535:
            normalized.append({"protocol": protocol, "start_port": start, "end_port": end})
    return normalized


def _ports(config: dict[str, Any]) -> dict[str, Any]:
    network = collect_network_inventory()
    ranges = _port_ranges(config)
    conflicts: list[dict[str, Any]] = []
    for item in ranges:
        occupied = network.get("tcp_listen" if item["protocol"] == "tcp" else "udp_listen", [])
        matches = [port for port in occupied if item["start_port"] <= int(port) <= item["end_port"]]
        if matches:
            conflicts.append({**item, "occupied": matches})
    return {
        "configured": bool(ranges),
        "ranges": ranges,
        "network": network,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "note": None if ranges else "No Controller-managed port ranges are cached locally yet.",
    }


def _doctor(config: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(config)
    service = _service_state()
    heartbeat = _heartbeat(config)
    capabilities = detect_capabilities()
    ports = _ports(config)
    host = _host()
    findings: list[dict[str, str]] = []

    def add(code: str, severity: str, message: str) -> None:
        findings.append({"code": code, "severity": severity, "message": message})

    if not identity["agent_id"] or not identity["node_id"]:
        add("identity_incomplete", "critical", "Agent identity is incomplete.")
    if not identity["enrolled"]:
        add("not_enrolled", "critical", "Agent has no permanent enrollment credential.")
    if not service["healthy"]:
        add("service_inactive", "critical", f"{SERVICE_NAME} is not active.")
    if not heartbeat["controller"].get("reachable"):
        add("controller_unreachable", "warning", "Controller /ping endpoint is unreachable.")
    if not ports["configured"]:
        add("port_ranges_not_cached", "info", "Managed port ranges are not cached in the local Agent config.")
    if ports["conflict_count"]:
        add("managed_port_conflict", "warning", "Observed sockets overlap one or more managed ranges.")
    if int(host["storage_root_free_bytes"]) < 5 * 1024**3:
        add("low_disk_space", "warning", "Root filesystem has less than 5 GiB free.")

    severities = {item["severity"] for item in findings}
    status = "critical" if "critical" in severities else "degraded" if "warning" in severities else "healthy"
    return {
        "schema_version": 1,
        "kind": "CapivaraAgentDoctor",
        "scope": "agent-local",
        "status": status,
        "ready": status != "critical",
        "identity": identity,
        "service": service,
        "heartbeat": heartbeat,
        "host": host,
        "capabilities": capabilities,
        "ports": ports,
        "findings": findings,
    }


def _logs(lines: int) -> dict[str, Any]:
    lines = max(1, min(int(lines), 2000))
    code, output = _run(
        ["journalctl", "-u", SERVICE_NAME, "-n", str(lines), "--no-pager", "--output=short-iso"],
        timeout=10,
    )
    return {"service": SERVICE_NAME, "ok": code == 0, "lines": output.splitlines() if output else []}


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                print(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
            else:
                print(f"{key}: {value}")
    else:
        print(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cap", description="Capivara Linux Agent local CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "info", "health", "heartbeat", "capabilities", "network", "doctor"):
        item = sub.add_parser(name)
        item.add_argument("--json", action="store_true", dest="as_json")
    ports = sub.add_parser("ports")
    ports_sub = ports.add_subparsers(dest="ports_action", required=True)
    for name in ("show", "check"):
        item = ports_sub.add_parser(name)
        item.add_argument("--json", action="store_true", dest="as_json")
    logs = sub.add_parser("logs")
    logs.add_argument("--lines", type=int, default=200)
    logs.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "agent":
        args_list.pop(0)
    args = _parser().parse_args(args_list)
    try:
        config = _read_config()
        if args.command == "status":
            identity = _identity(config)
            service = _service_state()
            controller = _controller_probe(config)
            payload = {
                "agent_id": identity["agent_id"],
                "node_id": identity["node_id"],
                "version": identity["version"],
                "enrolled": identity["enrolled"],
                "service": service["active_state"],
                "controller_reachable": controller.get("reachable", False),
            }
        elif args.command == "info":
            payload = {"identity": _identity(config), "host": _host()}
        elif args.command == "health":
            payload = {"service": _service_state(), "controller": _controller_probe(config)}
        elif args.command == "heartbeat":
            payload = _heartbeat(config)
        elif args.command == "capabilities":
            payload = detect_capabilities()
        elif args.command == "network":
            payload = collect_network_inventory()
        elif args.command == "ports":
            payload = _ports(config)
        elif args.command == "logs":
            payload = _logs(args.lines)
        elif args.command == "doctor":
            payload = _doctor(config)
        else:
            raise RuntimeError("unsupported command")
        _emit(payload, as_json=bool(getattr(args, "as_json", False)))
        if args.command == "doctor" and payload.get("status") == "critical":
            return 1
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
