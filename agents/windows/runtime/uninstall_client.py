#!/usr/bin/env python3
"""Typed two-phase remote uninstall client for the Windows Agent."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", PROGRAM_DATA / "CapivaraAgent" / "state"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "CapivaraAgent"))
REQUEST_PATH = STATE_DIR / "uninstall-request.json"
RESULT_PATH = STATE_DIR / "uninstall-result.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _ps_quote(value: Path) -> str:
    return str(value).replace("'", "''")


def read_result() -> dict[str, Any] | None:
    try:
        value = json.loads(RESULT_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def clear_result(request_id: str) -> None:
    current = read_result()
    if isinstance(current, dict) and str(current.get("request_id") or "") == str(request_id):
        RESULT_PATH.unlink(missing_ok=True)


def _validate(command: dict[str, Any]) -> tuple[str, str, str]:
    if str(command.get("kind") or "") != "AgentUninstallCommand":
        raise ValueError("invalid uninstall command kind")
    if int(command.get("schema_version") or 0) != 1:
        raise ValueError("unsupported uninstall command schema")
    if str(command.get("action") or "") != "uninstall-agent":
        raise ValueError("invalid uninstall action")
    request_id = str(command.get("request_id") or "").strip()
    mode = str(command.get("mode") or "").strip().lower()
    phase = str(command.get("phase") or "").strip().lower()
    if not request_id:
        raise ValueError("uninstall request_id is required")
    if mode not in {"preserve-data", "purge"}:
        raise ValueError("invalid uninstall mode")
    if phase not in {"prepare", "commit"}:
        raise ValueError("invalid uninstall phase")
    return request_id, mode, phase


def accept_command(command: dict[str, Any]) -> dict[str, Any]:
    request_id, mode, phase = _validate(command)
    if phase != "prepare":
        raise ValueError("prepare phase required")
    request = {
        "request_id": request_id,
        "mode": mode,
        "status": "accepted",
        "accepted_at": _now(),
    }
    _atomic_json(REQUEST_PATH, request)
    result = {
        "request_id": request_id,
        "status": "accepted",
        "accepted_at": request["accepted_at"],
    }
    _atomic_json(RESULT_PATH, result)
    return result


def commit(request_id: str) -> dict[str, Any]:
    request_id = str(request_id or "").strip()
    if not request_id:
        raise ValueError("uninstall request_id is required")
    try:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("staged uninstall request not found") from exc
    if not isinstance(request, dict) or str(request.get("request_id") or "") != request_id:
        raise RuntimeError("staged uninstall request does not match commit")
    mode = str(request.get("mode") or "").strip().lower()
    if str(request.get("status") or "").strip().lower() == "committed":
        return {
            "request_id": request_id,
            "status": "committed",
            "mode": mode,
            "committed_at": request.get("committed_at"),
        }
    script = INSTALL_ROOT / "service" / "uninstall-agent.ps1"
    if not script.is_file():
        raise RuntimeError("Windows Agent uninstall script is not installed")

    staging = Path(tempfile.gettempdir()) / f"capivara-uninstall-{request_id}.ps1"
    launch_lock = Path(tempfile.gettempdir()) / f"capivara-uninstall-{request_id}.launched"
    staging.write_bytes(script.read_bytes())
    command = (
        "$lock='" + _ps_quote(launch_lock) + "'; "
        + "try { $fs=[System.IO.File]::Open($lock,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None); $fs.Close() } "
        + "catch [System.IO.IOException] { exit 0 }; "
        + "Start-Sleep -Seconds 3; "
        + "& '" + _ps_quote(staging) + "' "
        + "-InstallRoot '" + _ps_quote(INSTALL_ROOT) + "' "
        + "-DataRoot '" + _ps_quote(STATE_DIR.parent) + "' "
        + ("-Purge " if mode == "purge" else "")
        + "; Remove-Item -LiteralPath '" + _ps_quote(staging) + "' -Force -ErrorAction SilentlyContinue"
    )
    arguments = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]
    flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    subprocess.Popen(arguments, creationflags=flags, close_fds=True)
    request["status"] = "committed"
    request["committed_at"] = _now()
    _atomic_json(REQUEST_PATH, request)
    result = {
        "request_id": request_id,
        "status": "committed",
        "mode": mode,
        "committed_at": request["committed_at"],
    }
    _atomic_json(RESULT_PATH, result)
    return result


def handle_command(command: dict[str, Any]) -> dict[str, Any]:
    request_id, _mode, phase = _validate(command)
    if phase == "prepare":
        return accept_command(command)
    return commit(request_id)
