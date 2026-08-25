#!/usr/bin/env python3
"""Execute trusted game-console transports on the Linux Agent.

The Controller sends only the game command text. Transport configuration and
credentials remain on the Agent-owned instance record. No shell is used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import instance_runtime

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RESULT_DIR = STATE_DIR / "console-results"
HISTORY_DIR = STATE_DIR / "console-history"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _path(root: Path, command_id: str) -> Path:
    safe = "".join(c for c in str(command_id or "") if c.isalnum() or c in "._-")
    if not safe or len(safe) > 191: raise ValueError("invalid console command id")
    return root / f"{safe}.json"


def _read(path: Path) -> dict[str, Any] | None:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None
    return value if isinstance(value, dict) else None


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.chmod(temp, 0o600); os.replace(temp, path)


def _tail(path_value: Any, limit: int = 120) -> list[str]:
    path = Path(str(path_value or ""))
    if not path.is_file(): return []
    try: return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError: return []


def _exec_transport(console: dict[str, Any], command: str) -> list[str]:
    template = console.get("command_argv")
    if not isinstance(template, list) or not template or not all(isinstance(x, str) for x in template):
        raise RuntimeError("console exec transport has no trusted command_argv")
    if not str(template[0]).startswith("/"):
        raise RuntimeError("console executable must use an absolute path")
    placeholders = sum(item.count("{command}") for item in template)
    if placeholders != 1:
        raise RuntimeError("console command_argv must contain one {command} placeholder")
    argv = [item.replace("{command}", command) for item in template]
    timeout = max(1, min(int(console.get("timeout_seconds") or 10), 30))
    result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)
    output = []
    if result.stdout: output.extend(result.stdout.rstrip().splitlines())
    if result.stderr: output.extend(result.stderr.rstrip().splitlines())
    if result.returncode != 0: raise RuntimeError(("\n".join(output) or f"console transport failed ({result.returncode})")[:2000])
    return output[-200:]


def _tmux_transport(console: dict[str, Any], command: str) -> list[str]:
    session = str(console.get("session") or "").strip()
    if not session or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in session):
        raise RuntimeError("invalid tmux console session")
    result = subprocess.run(["tmux", "send-keys", "-t", session, "--", command, "Enter"], capture_output=True, text=True, check=False, timeout=10)
    if result.returncode != 0: raise RuntimeError((result.stderr or result.stdout or "tmux console failed")[:2000])
    return _tail(console.get("output_file"))


def execute(config: dict[str, Any], instance_id: str, command: str) -> list[str]:
    record = instance_runtime.get_instance(instance_id)
    if not isinstance(record, dict): raise LookupError("instance not found")
    if str(record.get("agent_id") or "") != str(config.get("agent_id") or ""): raise PermissionError("instance belongs to another Agent")
    console = record.get("console") if isinstance(record.get("console"), dict) else {}
    if not bool(console.get("supported")): raise RuntimeError("runtime does not support game console")
    command = str(command or "").strip()
    if not command or len(command) > 512 or "\x00" in command or "\n" in command or "\r" in command: raise ValueError("invalid game console command")
    transport = str(console.get("transport") or "").lower()
    if transport == "exec": return _exec_transport(console, command)
    if transport == "tmux": return _tmux_transport(console, command)
    raise RuntimeError(f"unsupported game console transport: {transport or 'none'}")


def handle_command(config: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    command_id = str(command.get("command_id") or "").strip(); history = _path(HISTORY_DIR, command_id)
    previous = _read(history)
    if previous is not None: _write(_path(RESULT_DIR, command_id), previous); return previous
    instance_id = str(command.get("instance_id") or "").strip(); text = str(command.get("command_text") or "")
    try:
        output = execute(config, instance_id, text)
        result = {"command_id": command_id, "instance_id": instance_id, "status": "completed", "output": output, "generated_at": _now()}
    except Exception as exc:
        result = {"command_id": command_id, "instance_id": instance_id or None, "status": "failed", "error": str(exc)[:2000], "generated_at": _now()}
    _write(history, result); _write(_path(RESULT_DIR, command_id), result); return result


def read_result() -> dict[str, Any] | None:
    try: paths = sorted(RESULT_DIR.glob("*.json"))
    except OSError: paths = []
    for path in paths:
        value = _read(path)
        if value: return value
    return None


def clear_result(command_id: str) -> None:
    try: _path(RESULT_DIR, command_id).unlink()
    except FileNotFoundError: pass


def console_state(config: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in instance_runtime.list_instances(config):
        record = instance_runtime.get_instance(str(item.get("instance_id") or "")) or {}
        console = record.get("console") if isinstance(record.get("console"), dict) else {}
        if bool(console.get("supported")):
            result.append({"instance_id": record.get("instance_id"), "supported": True, "transport": console.get("transport"), "output": _tail(console.get("output_file"), 200)})
    return result


__all__ = ["clear_result", "console_state", "execute", "handle_command", "read_result"]
