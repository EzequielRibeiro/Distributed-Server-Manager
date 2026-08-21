#!/usr/bin/env python3
"""Local, read-only operational CLI for a standalone Linux Agent."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
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
from game_data_state import get_game_data, get_job, list_game_data, list_jobs, summary as game_data_summary
from instance_runtime import doctor as instance_doctor
from instance_runtime import list_instances as local_instances
from instance_runtime import status as instance_status
from network_inventory import collect_network_inventory
from update_state import history as update_history, status as update_status

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
SERVICE_NAME = os.environ.get("CAPIVARA_AGENT_SERVICE", "capivara-agent.service")
REPOSITORY = os.environ.get(
    "CAPIVARA_AGENT_GITHUB_REPOSITORY",
    "EzequielRibeiro/Distributed-Server-Manager",
)


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
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    output = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, output


def _service_state() -> dict[str, Any]:
    code, output = _run(["systemctl", "show", SERVICE_NAME, "--property=LoadState,ActiveState,SubState", "--value"])
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
    request = urllib.request.Request(base + "/ping", headers={"Accept": "application/json", "User-Agent": "Capivara-Agent-CLI"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"configured": True, "reachable": 200 <= int(response.status) < 300, "status_code": int(response.status), "response": body[:500]}
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
    return {"hostname": socket.gethostname(), "os": platform.system().lower(), "architecture": platform.machine(), "cpu_logical_cores": os.cpu_count(), "ram_total_bytes": _memory_total_bytes(), "storage_root_total_bytes": disk.total, "storage_root_free_bytes": disk.free}


def _identity(config: dict[str, Any]) -> dict[str, Any]:
    return {"agent_id": config.get("agent_id"), "node_id": config.get("node_id"), "name": config.get("name") or socket.gethostname(), "controller_id": config.get("controller_id"), "controller_url": config.get("controller_url"), "enrolled": bool(config.get("credential_id") and config.get("credential_secret")), "credential_type": config.get("credential_type"), "fingerprint": config.get("fingerprint"), "version": _installed_version(config)}


def _heartbeat(config: dict[str, Any]) -> dict[str, Any]:
    return {"interval_seconds": int(config.get("heartbeat_interval_seconds", 30)), "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)), "offline_after_seconds": int(config.get("offline_after_seconds", 120)), "controller": _controller_probe(config)}


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
            start = int(item.get("start_port")); end = int(item.get("end_port"))
        except (TypeError, ValueError):
            continue
        if protocol in {"tcp", "udp"} and 1 <= start <= end <= 65535:
            normalized.append({"protocol": protocol, "start_port": start, "end_port": end})
    return normalized


def _ports(config: dict[str, Any]) -> dict[str, Any]:
    network = collect_network_inventory(); ranges = _port_ranges(config); conflicts: list[dict[str, Any]] = []
    for item in ranges:
        occupied = network.get("tcp_listen" if item["protocol"] == "tcp" else "udp_listen", [])
        matches = [port for port in occupied if item["start_port"] <= int(port) <= item["end_port"]]
        if matches:
            conflicts.append({**item, "occupied": matches})
    return {"configured": bool(ranges), "ranges": ranges, "network": network, "conflicts": conflicts, "conflict_count": len(conflicts), "note": None if ranges else "No Controller-managed port ranges are cached locally yet."}


def _semver_key(value: str) -> tuple[int, int, int, int, str] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$", value.strip())
    if not match:
        return None
    major, minor, patch = (int(match.group(i)) for i in range(1, 4)); prerelease = match.group(4) or ""
    return major, minor, patch, 0 if prerelease else 1, prerelease


def _github_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Capivara-Agent-CLI", "X-GitHub-Api-Version": "2022-11-28"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        raise RuntimeError(f"GitHub Releases query failed: {exc}") from exc


def _update_check(config: dict[str, Any], channel: str) -> dict[str, Any]:
    channel = str(channel or "stable").lower()
    if channel not in {"stable", "beta"}:
        raise ValueError("update channel must be stable or beta")
    if channel == "stable":
        release = _github_json(f"https://api.github.com/repos/{REPOSITORY}/releases/latest")
    else:
        releases = _github_json(f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=20")
        if not isinstance(releases, list):
            raise RuntimeError("invalid GitHub Releases response")
        release = next((item for item in releases if isinstance(item, dict) and item.get("prerelease") and not item.get("draft")), None)
        if release is None:
            raise RuntimeError("no beta Agent release is available")
    if not isinstance(release, dict):
        raise RuntimeError("invalid GitHub release")
    tag = str(release.get("tag_name") or "").strip(); latest = tag[1:] if tag.startswith("v") else tag; installed = _installed_version(config)
    latest_key = _semver_key(latest); installed_key = _semver_key(installed)
    return {"source": "github-releases", "repository": REPOSITORY, "channel": channel, "installed_version": installed, "latest_version": latest or None, "update_available": bool(latest_key and installed_key and latest_key > installed_key), "release_url": release.get("html_url"), "asset_prefix": f"capivara-agent-linux-{latest}" if latest else None}


def _doctor(config: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(config); service = _service_state(); heartbeat = _heartbeat(config); capabilities = detect_capabilities(); ports = _ports(config); host = _host(); game_data = game_data_summary(); updates = update_status(); findings: list[dict[str, str]] = []
    def add(code: str, severity: str, message: str) -> None: findings.append({"code": code, "severity": severity, "message": message})
    if not identity["agent_id"] or not identity["node_id"]: add("identity_incomplete", "critical", "Agent identity is incomplete.")
    if not identity["enrolled"]: add("not_enrolled", "critical", "Agent has no permanent enrollment credential.")
    if not service["healthy"]: add("service_inactive", "critical", f"{SERVICE_NAME} is not active.")
    if not heartbeat["controller"].get("reachable"): add("controller_unreachable", "warning", "Controller /ping endpoint is unreachable.")
    if not ports["configured"]: add("port_ranges_not_cached", "info", "Managed port ranges are not cached in the local Agent config.")
    if ports["conflict_count"]: add("managed_port_conflict", "warning", "Observed sockets overlap one or more managed ranges.")
    if int(host["storage_root_free_bytes"]) < 5 * 1024**3: add("low_disk_space", "warning", "Root filesystem has less than 5 GiB free.")
    if int(game_data.get("failed_recent_jobs", 0)): add("recent_game_data_failures", "warning", "One or more recent local game-data jobs failed.")
    last_update = updates.get("last_result") or {}
    if isinstance(last_update, dict) and last_update.get("status") == "failed": add("recent_update_failure", "warning", "The most recent Agent update failed.")
    severities = {item["severity"] for item in findings}; status_value = "critical" if "critical" in severities else "degraded" if "warning" in severities else "healthy"
    return {"schema_version": 1, "kind": "CapivaraAgentDoctor", "scope": "agent-local", "status": status_value, "ready": status_value != "critical", "identity": identity, "service": service, "heartbeat": heartbeat, "host": host, "capabilities": capabilities, "ports": ports, "game_data": game_data, "updates": updates, "findings": findings}


def _logs(lines: int) -> dict[str, Any]:
    lines = max(1, min(int(lines), 2000)); code, output = _run(["journalctl", "-u", SERVICE_NAME, "-n", str(lines), "--no-pager", "--output=short-iso"], timeout=10)
    return {"service": SERVICE_NAME, "ok": code == 0, "lines": output.splitlines() if output else []}


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str)); return
    if isinstance(payload, dict):
        for key, value in payload.items(): print(f"{key}: {json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value}")
    elif isinstance(payload, list):
        for item in payload: print(json.dumps(item, ensure_ascii=False, default=str))
    else: print(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cap", description="Capivara Linux Agent local CLI"); sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "info", "health", "heartbeat", "capabilities", "network", "doctor"):
        item = sub.add_parser(name); item.add_argument("--json", action="store_true", dest="as_json")
    ports = sub.add_parser("ports"); ports_sub = ports.add_subparsers(dest="ports_action", required=True)
    for name in ("show", "check"):
        item = ports_sub.add_parser(name); item.add_argument("--json", action="store_true", dest="as_json")
    game_data = sub.add_parser("game-data"); game_data_sub = game_data.add_subparsers(dest="game_data_action", required=True)
    game_list = game_data_sub.add_parser("list"); game_list.add_argument("--json", action="store_true", dest="as_json")
    game_status = game_data_sub.add_parser("status"); game_status.add_argument("game"); game_status.add_argument("--json", action="store_true", dest="as_json")
    jobs = sub.add_parser("jobs"); jobs.add_argument("--active", action="store_true"); jobs.add_argument("--limit", type=int, default=50); jobs.add_argument("--json", action="store_true", dest="as_json"); jobs_sub = jobs.add_subparsers(dest="jobs_action")
    job_show = jobs_sub.add_parser("show"); job_show.add_argument("job_id"); job_show.add_argument("--json", action="store_true", dest="as_json")
    update = sub.add_parser("update"); update_sub = update.add_subparsers(dest="update_action", required=True)
    update_status_parser = update_sub.add_parser("status"); update_status_parser.add_argument("--json", action="store_true", dest="as_json")
    update_history_parser = update_sub.add_parser("history"); update_history_parser.add_argument("--limit", type=int, default=20); update_history_parser.add_argument("--json", action="store_true", dest="as_json")
    update_check_parser = update_sub.add_parser("check"); update_check_parser.add_argument("--channel", choices=("stable", "beta"), default="stable"); update_check_parser.add_argument("--json", action="store_true", dest="as_json")
    logs = sub.add_parser("logs"); logs.add_argument("--lines", type=int, default=200); logs.add_argument("--json", action="store_true", dest="as_json")
    instance = sub.add_parser("instance"); instance_sub = instance.add_subparsers(dest="instance_action", required=True)
    instance_list = instance_sub.add_parser("list"); instance_list.add_argument("--json", action="store_true", dest="as_json")
    for name in ("status", "doctor"):
        item = instance_sub.add_parser(name); item.add_argument("instance_id"); item.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "agent": args_list.pop(0)
    args = _parser().parse_args(args_list)
    try:
        config = _read_config()
        if args.command == "status":
            identity = _identity(config); service = _service_state(); controller = _controller_probe(config); payload = {"agent_id": identity["agent_id"], "node_id": identity["node_id"], "version": identity["version"], "enrolled": identity["enrolled"], "service": service["active_state"], "controller_reachable": controller.get("reachable", False)}
        elif args.command == "info": payload = {"identity": _identity(config), "host": _host()}
        elif args.command == "health": payload = {"service": _service_state(), "controller": _controller_probe(config)}
        elif args.command == "heartbeat": payload = _heartbeat(config)
        elif args.command == "capabilities": payload = detect_capabilities()
        elif args.command == "network": payload = collect_network_inventory()
        elif args.command == "ports": payload = _ports(config)
        elif args.command == "game-data":
            if args.game_data_action == "list": payload = {"games": list_game_data()}
            else:
                payload = get_game_data(args.game)
                if payload is None: raise LookupError(f"game-data not found: {args.game}")
        elif args.command == "jobs":
            if args.jobs_action == "show":
                payload = get_job(args.job_id)
                if payload is None: raise LookupError(f"job not found: {args.job_id}")
            else: payload = {"jobs": list_jobs(active_only=bool(args.active), limit=args.limit)}
        elif args.command == "update":
            if args.update_action == "status": payload = update_status()
            elif args.update_action == "history": payload = {"updates": update_history(limit=args.limit)}
            else: payload = _update_check(config, args.channel)
        elif args.command == "logs": payload = _logs(args.lines)
        elif args.command == "doctor": payload = _doctor(config)
        elif args.command == "instance":
            if args.instance_action == "list": payload = {"instances": local_instances(config)}
            elif args.instance_action == "status": payload = instance_status(config, args.instance_id)
            else: payload = instance_doctor(config, args.instance_id)
        else: raise RuntimeError("unsupported command")
        _emit(payload, as_json=bool(getattr(args, "as_json", False)))
        if args.command == "doctor" and payload.get("status") == "critical": return 1
        if args.command == "instance" and args.instance_action == "doctor" and payload.get("status") == "critical": return 1
        return 0
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    except PermissionError as exc:
        print(f"error: {exc}", file=sys.stderr); return 3
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
