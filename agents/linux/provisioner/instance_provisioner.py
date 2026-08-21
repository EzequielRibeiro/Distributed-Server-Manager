#!/usr/bin/env python3
"""Privileged, rollback-safe materializer for Agent-owned instance services."""

from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
RUNTIME_DIR = INSTALL_ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from game_data_state import get_game_data

ROOT = STATE_DIR / "instance-provisioning"
REQUEST_DIR = ROOT / "requests"
RESULT_DIR = ROOT / "results"
HISTORY_DIR = ROOT / "history"
INSTANCE_DATA_ROOT = Path(os.environ.get("CAPIVARA_INSTANCE_DATA_ROOT", str(STATE_DIR / "instance-data")))
SYSTEMD_DIR = Path(os.environ.get("CAPIVARA_SYSTEMD_DIR", "/etc/systemd/system"))
SERVICE_USER = os.environ.get("CAPIVARA_AGENT_USER", "capivara-agent")
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
VALID_ACTIONS = {"provision", "reconcile", "remove"}
VALID_ENGINES = {"native", "java"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _state_owner() -> tuple[int, int]:
    entry = pwd.getpwnam(SERVICE_USER)
    return entry.pw_uid, entry.pw_gid


def _ensure_dir(path: Path, mode: int = 0o700, *, agent_owned: bool = True) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    if agent_owned:
        uid, gid = _state_owner()
        os.chown(path, uid, gid)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    uid, gid = _state_owner()
    os.chown(temp, uid, gid)
    os.replace(temp, path)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("provisioning request must be an object")
    return value


def unit_for_instance(instance_id: str) -> str:
    return f"capivara-instance-{_token(instance_id, 'instance_id')}.service"


def instance_root(instance_id: str) -> Path:
    return INSTANCE_DATA_ROOT / _token(instance_id, "instance_id")


def _quote(value: str) -> str:
    if any(ch in value for ch in ("\x00", "\n", "\r", "$")):
        raise ValueError("unsupported character in systemd argument")
    escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _runtime_contract(request: dict[str, Any]) -> dict[str, Any]:
    runtime = request.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("runtime contract is required")
    if str(runtime.get("adapter") or "").strip().lower() != "systemd":
        raise ValueError("only the systemd instance adapter is supported")
    game_id = _token(runtime.get("game_id"), "game_id")
    runtime_id = _token(runtime.get("runtime_id"), "runtime_id")
    environment_id = _token(runtime.get("environment_id") or runtime_id, "environment_id")
    launch = runtime.get("launch")
    if not isinstance(launch, dict):
        raise ValueError("runtime launch profile is required")
    engine = str(launch.get("engine") or "").strip().lower()
    if engine not in VALID_ENGINES:
        raise ValueError("unsupported runtime launch engine")
    executable_text = str(launch.get("executable") or "").strip()
    executable = PurePosixPath(executable_text)
    if not executable_text or executable.is_absolute() or ".." in executable.parts:
        raise ValueError("launch executable must be a relative game-data path")
    arguments = launch.get("arguments", [])
    if not isinstance(arguments, list) or len(arguments) > 64:
        raise ValueError("launch arguments must contain at most 64 entries")
    clean_arguments: list[str] = []
    for item in arguments:
        value = str(item)
        if len(value) > 1024:
            raise ValueError("launch argument is too long")
        _quote(value)
        clean_arguments.append(value)
    return {
        "adapter": "systemd",
        "game_id": game_id,
        "runtime_id": runtime_id,
        "environment_id": environment_id,
        "engine": engine,
        "launch_executable": executable.as_posix(),
        "arguments": clean_arguments,
    }


def _run(command: list[str], timeout: int = 30, *, check: bool = True) -> tuple[int, str]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    output = (completed.stderr or completed.stdout or "").strip()
    if check and completed.returncode != 0:
        raise RuntimeError((output or "command failed")[:2000])
    return completed.returncode, output


def _unit_active(unit_name: str) -> bool:
    code, _ = _run(["systemctl", "is-active", "--quiet", unit_name], timeout=10, check=False)
    return code == 0


def _daemon_reload() -> None:
    _run(["systemctl", "daemon-reload"], timeout=30)


def _launch_argv(runtime: dict[str, Any], artifact: Path) -> list[str]:
    if runtime["engine"] == "native":
        if not os.access(artifact, os.X_OK):
            raise RuntimeError("native launch executable is not executable")
        return [str(artifact), *runtime["arguments"]]
    java = shutil.which("java")
    if not java:
        raise RuntimeError("Java runtime is required but was not found on the Agent")
    return [str(Path(java).resolve()), "-jar", str(artifact), *runtime["arguments"]]


def render_unit(instance_id: str, argv: list[str], working_dir: Path) -> str:
    if not argv:
        raise ValueError("launch argv is empty")
    root = instance_root(instance_id)
    return "\n".join([
        "[Unit]",
        f"Description=Capivara DSM instance {instance_id}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={SERVICE_USER}",
        f"Group={SERVICE_USER}",
        f"WorkingDirectory={_quote(str(working_dir))}",
        "ExecStart=" + " ".join(_quote(item) for item in argv),
        "Restart=on-failure",
        "RestartSec=5",
        "UMask=0077",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        f"ReadWritePaths={_quote(str(root))}",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])


def _verify_unit(unit_name: str, content: str) -> None:
    with tempfile.TemporaryDirectory(prefix="capivara-instance-unit-") as temporary:
        candidate = Path(temporary) / unit_name
        candidate.write_text(content, encoding="utf-8")
        _run(["systemd-analyze", "verify", str(candidate)], timeout=20)


def _resolve_game_artifact(runtime: dict[str, Any]) -> tuple[Path, Path]:
    state = get_game_data(runtime["game_id"])
    if not state or not state.get("installed"):
        raise RuntimeError(f"game-data is not installed: {runtime['game_id']}")
    target_text = str(state.get("target_path") or "").strip()
    if not target_text:
        raise RuntimeError("game-data target path is missing")
    target = Path(target_text).resolve()
    if not target.is_dir():
        raise RuntimeError("game-data target path is unavailable")
    artifact = (target / runtime["launch_executable"]).resolve()
    try:
        artifact.relative_to(target)
    except ValueError as exc:
        raise RuntimeError("launch artifact escapes game-data root") from exc
    if not artifact.is_file():
        raise RuntimeError("launch artifact is missing")
    return target, artifact


def _prepare_instance_dirs(instance_id: str) -> tuple[Path, Path]:
    root = instance_root(instance_id)
    working = root / "serverfiles"
    _ensure_dir(INSTANCE_DATA_ROOT, 0o750)
    _ensure_dir(root, 0o750)
    _ensure_dir(working, 0o750)
    return root, working


def _write_unit_transactional(unit_path: Path, content: str) -> bool:
    old = unit_path.read_bytes() if unit_path.is_file() else None
    changed = old != content.encode("utf-8")
    if not changed:
        return False
    temp = unit_path.with_name(f".{unit_path.name}.{os.getpid()}.tmp")
    try:
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(content, encoding="utf-8")
        os.chmod(temp, 0o644)
        os.replace(temp, unit_path)
        _daemon_reload()
    except Exception:
        temp.unlink(missing_ok=True)
        if old is None:
            unit_path.unlink(missing_ok=True)
        else:
            rollback = unit_path.with_name(f".{unit_path.name}.rollback")
            rollback.write_bytes(old)
            os.chmod(rollback, 0o644)
            os.replace(rollback, unit_path)
        try:
            _daemon_reload()
        except Exception:
            pass
        raise
    return True


def _remove_unit(unit_name: str, unit_path: Path) -> bool:
    old = unit_path.read_bytes() if unit_path.is_file() else None
    was_active = _unit_active(unit_name)
    if was_active:
        _run(["systemctl", "stop", unit_name, "--no-pager"], timeout=30)
    if old is None:
        return False
    try:
        unit_path.unlink()
        _daemon_reload()
    except Exception:
        rollback = unit_path.with_name(f".{unit_path.name}.rollback")
        rollback.write_bytes(old)
        os.chmod(rollback, 0o644)
        os.replace(rollback, unit_path)
        try:
            _daemon_reload()
            if was_active:
                _run(["systemctl", "start", unit_name, "--no-pager"], timeout=30, check=False)
        except Exception:
            pass
        raise
    return True


def _materialize(request: dict[str, Any]) -> dict[str, Any]:
    job_id = _token(request.get("job_id"), "job_id")
    instance_id = _token(request.get("instance_id"), "instance_id")
    agent_id = _token(request.get("agent_id"), "agent_id")
    action = str(request.get("action") or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError("unsupported provisioning action")
    unit_name = unit_for_instance(instance_id)
    unit_path = SYSTEMD_DIR / unit_name

    if action == "remove":
        removed = _remove_unit(unit_name, unit_path)
        return {
            "job_id": job_id,
            "instance_id": instance_id,
            "agent_id": agent_id,
            "action": action,
            "status": "completed",
            "unit": unit_name,
            "unit_removed": removed,
            "data_preserved": True,
            "generated_at": _now(),
        }

    runtime = _runtime_contract(request)
    game_data_path, artifact = _resolve_game_artifact(runtime)
    root, working = _prepare_instance_dirs(instance_id)
    argv = _launch_argv(runtime, artifact)
    content = render_unit(instance_id, argv, working)
    _verify_unit(unit_name, content)
    old_content = unit_path.read_text(encoding="utf-8") if unit_path.is_file() else None
    if action == "reconcile" and old_content != content and _unit_active(unit_name):
        raise RuntimeError("stop the instance before reconciling a changed unit")
    changed = _write_unit_transactional(unit_path, content)
    record = {
        "schema_version": 3,
        "kind": "CapivaraAgentInstance",
        "instance_id": instance_id,
        "agent_id": agent_id,
        "game_id": runtime["game_id"],
        "environment_id": runtime["environment_id"],
        "runtime_id": runtime["runtime_id"],
        "adapter": "systemd",
        "unit": unit_name,
        "path": str(root),
        "serverfiles_path": str(working),
        "game_data_path": str(game_data_path),
        "launch_profile": {
            "engine": runtime["engine"],
            "executable": runtime["launch_executable"],
            "arguments": runtime["arguments"],
        },
        "provisioning_status": "ready",
        "desired_state": "stopped",
        "observed_state": "stopped",
    }
    return {
        "job_id": job_id,
        "instance_id": instance_id,
        "agent_id": agent_id,
        "action": action,
        "status": "completed",
        "unit": unit_name,
        "unit_changed": changed,
        "instance_record": record,
        "generated_at": _now(),
    }


def process_request(path: Path) -> dict[str, Any]:
    request = _read(path)
    job_id = _token(request.get("job_id"), "job_id")
    result_path = RESULT_DIR / f"{job_id}.json"
    history_path = HISTORY_DIR / f"{job_id}.json"
    try:
        previous = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    if isinstance(previous, dict) and str(previous.get("status") or "") in {"completed", "failed"}:
        _write_json(result_path, previous)
        return previous
    try:
        result = _materialize(request)
    except Exception as exc:
        result = {
            "job_id": job_id,
            "instance_id": request.get("instance_id"),
            "agent_id": request.get("agent_id"),
            "action": request.get("action"),
            "status": "failed",
            "error": str(exc)[:2000],
            "generated_at": _now(),
        }
    _write_json(result_path, result)
    _write_json(history_path, result)
    return result


def run_pending() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("instance provisioner must run as root")
    for directory in (REQUEST_DIR, RESULT_DIR, HISTORY_DIR):
        _ensure_dir(directory)
    processed = 0
    for path in sorted(REQUEST_DIR.glob("*.json")):
        process_request(path)
        processed += 1
    return processed


def main() -> int:
    try:
        run_pending()
        return 0
    except Exception as exc:
        print(f"instance provisioner failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
