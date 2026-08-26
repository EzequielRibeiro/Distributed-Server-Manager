#!/usr/bin/env python3
"""Execute a fixed read-only Doctor contract on a Windows Agent."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from capabilities import detect_capabilities
from game_data_state import summary as game_data_summary
from network_inventory import collect_network_inventory

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
RESULT_PATH = STATE_DIR / "doctor-result.json"
SERVICE_NAME = os.environ.get("CAPIVARA_AGENT_SERVICE", "CapivaraAgent")


def _controller(config: dict[str, Any]) -> dict[str, Any]:
    base = str(config.get("controller_url") or "").strip().rstrip("/")
    if not base:
        return {"configured": False, "reachable": False, "error": "controller_url is missing"}
    req = urllib.request.Request(base + "/ping", headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return {"configured": True, "reachable": 200 <= response.status < 300, "status_code": response.status}
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        return {"configured": True, "reachable": False, "error": str(exc)}


def _service() -> dict[str, Any]:
    try:
        completed = subprocess.run(["sc.exe", "query", SERVICE_NAME], capture_output=True, text=True, timeout=5, check=False)
        output = (completed.stdout or completed.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"service": SERVICE_NAME, "healthy": False, "error": str(exc)}
    running = completed.returncode == 0 and "RUNNING" in output.upper()
    return {"service": SERVICE_NAME, "healthy": running, "state": "running" if running else "inactive", "query_ok": completed.returncode == 0}


def _memory_total() -> int | None:
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        state = MEMORYSTATUSEX(); state.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            return int(state.ullTotalPhys)
    except Exception:
        pass
    return None


def _doctor(config: dict[str, Any]) -> dict[str, Any]:
    root = Path(os.environ.get("SystemDrive", "C:") + "\\")
    disk = shutil.disk_usage(root)
    service = _service()
    controller = _controller(config)
    capabilities = detect_capabilities()
    findings: list[dict[str, str]] = []
    def add(code: str, severity: str, message: str) -> None:
        findings.append({"code": code, "severity": severity, "message": message})
    if not config.get("agent_id") or not config.get("node_id"):
        add("identity_incomplete", "critical", "Agent identity is incomplete.")
    if not config.get("credential_id") or not config.get("credential_secret"):
        add("not_enrolled", "critical", "Agent has no permanent enrollment credential.")
    if not service.get("healthy"):
        add("service_inactive", "critical", f"{SERVICE_NAME} is not running.")
    if not controller.get("reachable"):
        add("controller_unreachable", "warning", "Controller /ping endpoint is unreachable.")
    if not config.get("advertise_address"):
        add("advertise_address_missing", "info", "Agent advertise_address is not configured.")
    if disk.free < 5 * 1024**3:
        add("low_disk_space", "warning", "System drive has less than 5 GiB free.")
    game_data = game_data_summary()
    if int(game_data.get("failed_recent_jobs", 0)):
        add("recent_game_data_failures", "warning", "One or more recent local game-data jobs failed.")
    steamcmd = capabilities.get("steamcmd_status") if isinstance(capabilities.get("steamcmd_status"), dict) else {}
    if steamcmd.get("installed") and not steamcmd.get("functional", True):
        add("steamcmd_not_functional", "warning", "SteamCMD is installed but failed its validation probe.")
    severities = {item["severity"] for item in findings}
    status = "critical" if "critical" in severities else "degraded" if "warning" in severities else "healthy"
    return {
        "schema_version": 1,
        "kind": "CapivaraAgentDoctor",
        "scope": "agent-local",
        "status": status,
        "ready": status != "critical",
        "identity": {
            "agent_id": config.get("agent_id"), "node_id": config.get("node_id"), "controller_id": config.get("controller_id"),
            "controller_url": config.get("controller_url"), "fingerprint": config.get("fingerprint"),
            "enrolled": bool(config.get("credential_id") and config.get("credential_secret")),
        },
        "service": service,
        "heartbeat": {
            "interval_seconds": int(config.get("heartbeat_interval_seconds", 30)),
            "degraded_after_seconds": int(config.get("degraded_after_seconds", 60)),
            "offline_after_seconds": int(config.get("offline_after_seconds", 120)),
            "controller": controller,
        },
        "host": {
            "hostname": socket.gethostname(), "os": "windows", "architecture": platform.machine(),
            "cpu_logical_cores": os.cpu_count(), "ram_total_bytes": _memory_total(),
            "storage_root_total_bytes": disk.total, "storage_root_free_bytes": disk.free,
            "network": collect_network_inventory(),
        },
        "capabilities": capabilities,
        "ports": {"configured": bool(config.get("port_ranges")), "ranges": config.get("port_ranges") or [], "conflict_count": 0},
        "game_data": game_data,
        "findings": findings,
    }


def _write(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = RESULT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(RESULT_PATH)


def handle_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    request_id = str(command.get("request_id") or "").strip()
    if not request_id:
        raise ValueError("doctor request_id is required")
    current = read_result()
    if current and current.get("request_id") == request_id:
        return current
    try:
        payload = {"request_id": request_id, "status": "completed", "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "result": _doctor(config)}
    except Exception as exc:
        payload = {"request_id": request_id, "status": "failed", "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error": str(exc)[:2000]}
    _write(payload)
    return payload


def read_result() -> dict[str, Any] | None:
    try:
        value = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def clear_result(request_id: str | None = None) -> None:
    current = read_result()
    if request_id and current and str(current.get("request_id")) != str(request_id):
        return
    try:
        RESULT_PATH.unlink()
    except FileNotFoundError:
        pass
