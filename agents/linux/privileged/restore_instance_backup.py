#!/usr/bin/env python3
"""Root-owned helper for atomic restore of a Hybrid instance backup."""

from __future__ import annotations

import json
import os
import pwd
import sys
from pathlib import Path
from typing import Any

INSTALL_ROOT = Path(
    os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent")
)
RUNTIME_DIR = INSTALL_ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import backup_client

STATE_DIR = Path(
    os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent")
)
CONFIG_PATH = Path(
    os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json")
)
REQUEST_ROOT = STATE_DIR / "privileged-backup-restore"


def _token(value: Any, label: str, max_length: int = 191) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if (
        not text
        or len(text) > max_length
        or any(ch not in allowed for ch in text)
    ):
        raise ValueError(f"invalid {label}")
    return text


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    try:
        account = pwd.getpwnam(
            os.environ.get("CAPIVARA_AGENT_RESULT_USER", "capivara-agent")
        )
        os.chown(temp, account.pw_uid, account.pw_gid)
    except (KeyError, OSError):
        pass
    os.replace(temp, path)


def run(command_id: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("privileged backup restore helper must run as root")

    command_id = _token(command_id, "command_id")
    request_path = REQUEST_ROOT / f"{command_id}.request.json"
    result_path = REQUEST_ROOT / f"{command_id}.result.json"

    request = json.loads(request_path.read_text(encoding="utf-8"))
    if (
        not isinstance(request, dict)
        or request.get("kind") != "CapivaraPrivilegedBackupRestoreRequest"
    ):
        raise RuntimeError("invalid privileged backup restore request")
    if str(request.get("command_id") or "") != command_id:
        raise RuntimeError("privileged backup restore command_id mismatch")
    if str(request.get("action") or "").strip().lower() != "restore":
        raise RuntimeError("privileged backup restore action must be restore")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RuntimeError("Agent config must be a JSON object")

    local_agent_id = str(config.get("agent_id") or "").strip()
    if not local_agent_id:
        raise RuntimeError("local Agent identity is unavailable")
    if str(request.get("agent_id") or "") != local_agent_id:
        raise PermissionError(
            "privileged backup restore request belongs to another Agent"
        )

    instance_id = _token(request.get("instance_id"), "instance_id")
    backup_id = _token(request.get("backup_id"), "backup_id")

    operation = backup_client._restore_direct(
        config,
        {
            "command_id": command_id,
            "instance_id": instance_id,
            "action": "restore",
            "backup_id": backup_id,
        },
    )

    result = {
        "status": "completed",
        "action": "restore",
        "command_id": command_id,
        "instance_id": instance_id,
        "agent_id": local_agent_id,
        "backup_id": backup_id,
        "operation": operation,
    }
    _write_result(result_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: restore_instance_backup.py COMMAND_ID",
            file=sys.stderr,
        )
        return 2

    command_id = args[0]
    try:
        safe_command_id = _token(command_id, "command_id")
    except Exception as exc:
        print(f"privileged backup restore failed: {exc}", file=sys.stderr)
        return 1

    result_path = REQUEST_ROOT / f"{safe_command_id}.result.json"
    try:
        result = run(safe_command_id)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        _write_result(
            result_path,
            {
                "status": "failed",
                "command_id": safe_command_id,
                "error": str(exc)[:2000],
            },
        )
        print(
            f"privileged backup restore failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
