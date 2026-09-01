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
CONFIG_PATH = Path(
    os.environ.get(
        "CAPIVARA_AGENT_CONFIG",
        STATE_DIR.parent / "agent.json",
    )
)
TEMP_DIR = Path(
    os.environ.get("CAPIVARA_AGENT_TEMP_DIR", tempfile.gettempdir())
)


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


def _safe_request_id(request_id: str) -> str:
    return "".join(
        ch for ch in str(request_id)
        if ch.isalnum() or ch in "-_"
    )[:80]


def _terminal_identity_path(request_id: str) -> Path:
    return TEMP_DIR / (
        f"capivara-uninstall-terminal-"
        f"{_safe_request_id(request_id)}.json"
    )


def _stage_terminal_identity(request_id: str) -> Path:
    try:
        config = json.loads(
            CONFIG_PATH.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            "Agent identity is unavailable for terminal "
            "uninstall result"
        ) from exc

    if not isinstance(config, dict):
        raise RuntimeError(
            "Agent identity is invalid for terminal "
            "uninstall result"
        )

    required = (
        "controller_url",
        "agent_id",
        "fingerprint",
        "credential_id",
        "credential_secret",
    )

    missing = [
        key
        for key in required
        if not str(config.get(key) or "").strip()
    ]

    if missing:
        raise RuntimeError(
            "Agent identity is incomplete for terminal "
            "uninstall result"
        )

    identity = {
        "controller_url": str(
            config["controller_url"]
        ).strip(),
        "agent_id": str(
            config["agent_id"]
        ).strip(),
        "fingerprint": str(
            config["fingerprint"]
        ).strip(),
        "credential_id": str(
            config["credential_id"]
        ).strip(),
        "credential_secret": str(
            config["credential_secret"]
        ),
        "request_id": str(request_id).strip(),
    }

    path = _terminal_identity_path(request_id)

    _atomic_json(path, identity)

    if os.name == "nt":
        try:
            subprocess.run(
                [
                    "icacls.exe",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    "*S-1-5-18:F",
                ],
                check=True,
                capture_output=True,
                text=True,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                ),
            )
        except (
            subprocess.CalledProcessError,
            OSError,
        ) as exc:
            path.unlink(missing_ok=True)
            raise RuntimeError(
                "failed to protect terminal uninstall identity"
            ) from exc

    return path


def _launch_paths(request_id: str) -> tuple[Path, Path]:
    staging = TEMP_DIR / f"capivara-uninstall-{request_id}.ps1"
    launch_lock = TEMP_DIR / f"capivara-uninstall-{request_id}.launched"
    return staging, launch_lock


def _launch_uninstall(request_id: str, mode: str) -> bool:
    """Launch uninstall through an independent SYSTEM Scheduled Task."""
    script = INSTALL_ROOT / "service" / "uninstall-agent.ps1"
    if not script.is_file():
        raise RuntimeError("Windows Agent uninstall script is not installed")

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    staging, launch_lock = _launch_paths(request_id)
    staging.write_bytes(script.read_bytes())

    try:
        fd = os.open(
            str(launch_lock),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError:
        return False
    os.close(fd)

    safe_id = _safe_request_id(request_id)
    task_name = f"CapivaraAgent-Uninstall-{safe_id}"
    terminal_identity = _stage_terminal_identity(
        request_id
    )

    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )

    uninstall_arguments = [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(staging),
        "-InstallRoot",
        str(INSTALL_ROOT),
        "-DataRoot",
        str(STATE_DIR.parent),
        "-LauncherTaskName",
        task_name,
        "-TerminalIdentityPath",
        str(terminal_identity),
        "-LaunchLockPath",
        str(launch_lock),
    ]
    if mode == "purge":
        uninstall_arguments.append("-Purge")

    task_arguments = subprocess.list2cmdline(
        uninstall_arguments
    )

    register_script = TEMP_DIR / (
        f"capivara-uninstall-register-{safe_id}.ps1"
    )

    register_script.write_text(
        """param(
[Parameter(Mandatory=$true)][string]$TaskName,
[Parameter(Mandatory=$true)][string]$Execute,
[Parameter(Mandatory=$true)][string]$Arguments
)
$ErrorActionPreference = "Stop"
$action = New-ScheduledTaskAction -Execute $Execute -Argument $Arguments
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
""",
        encoding="utf-8",
    )

    creation_flags = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )

    try:
        subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(register_script),
                "-TaskName",
                task_name,
                "-Execute",
                str(powershell),
                "-Arguments",
                task_arguments,
            ],
            check=True,
            capture_output=True,
            text=True,
            creationflags=creation_flags,
        )

        subprocess.run(
            [
                "schtasks.exe",
                "/Run",
                "/TN",
                task_name,
            ],
            check=True,
            capture_output=True,
            text=True,
            creationflags=creation_flags,
        )

    except (subprocess.CalledProcessError, OSError) as exc:
        launch_lock.unlink(missing_ok=True)
        terminal_identity.unlink(missing_ok=True)

        try:
            subprocess.run(
                [
                    "schtasks.exe",
                    "/Delete",
                    "/TN",
                    task_name,
                    "/F",
                ],
                check=False,
                capture_output=True,
                text=True,
                creationflags=creation_flags,
            )
        except OSError:
            pass

        stderr = str(getattr(exc, "stderr", "") or "").strip()
        stdout = str(getattr(exc, "stdout", "") or "").strip()
        detail = stderr or stdout or str(exc)

        raise RuntimeError(
            "failed to launch Windows uninstall task: "
            + detail
        ) from exc

    finally:
        register_script.unlink(missing_ok=True)

    return True
def resume_pending_commit() -> bool:
    """Recover a committed request whose detached launcher never started."""
    try:
        request = json.loads(
            REQUEST_PATH.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError, TypeError):
        return False

    if not isinstance(request, dict):
        return False
    if str(request.get("status") or "").strip().lower() != "committed":
        return False

    request_id = str(request.get("request_id") or "").strip()
    mode = str(request.get("mode") or "").strip().lower()

    if not request_id or mode not in {"preserve-data", "purge"}:
        return False

    _staging, launch_lock = _launch_paths(request_id)
    if launch_lock.exists():
        return False

    return _launch_uninstall(request_id, mode)


def commit(request_id: str) -> dict[str, Any]:
    request_id = str(request_id or "").strip()
    if not request_id:
        raise ValueError("uninstall request_id is required")

    try:
        request = json.loads(
            REQUEST_PATH.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("staged uninstall request not found") from exc

    if (
        not isinstance(request, dict)
        or str(request.get("request_id") or "") != request_id
    ):
        raise RuntimeError(
            "staged uninstall request does not match commit"
        )

    mode = str(request.get("mode") or "").strip().lower()
    if mode not in {"preserve-data", "purge"}:
        raise RuntimeError("invalid staged uninstall mode")

    if str(request.get("status") or "").strip().lower() == "committed":
        # A previous Python process may have persisted committed immediately
        # before a launcher failure. Recover only when the atomic launch lock
        # proves that handoff never occurred.
        _staging, launch_lock = _launch_paths(request_id)
        if not launch_lock.exists():
            _launch_uninstall(request_id, mode)

        return {
            "request_id": request_id,
            "status": "committed",
            "mode": mode,
            "committed_at": request.get("committed_at"),
        }

    # Do not persist committed until process creation itself succeeds.
    _launch_uninstall(request_id, mode)

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
