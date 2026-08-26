#!/usr/bin/env python3
"""Root-owned helper that applies/removes only validated Capivara instance runtimes."""
from __future__ import annotations

import grp
import json
import os
import pwd
import shutil
import sys
from pathlib import Path
from typing import Any

INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
RUNTIME_DIR = INSTALL_ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from catalog_runtime_policy import materialize_network_properties, materialize_templates
from materializers import resolve_materializer
from runtime_spec import validate_runtime_spec

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
REQUEST_ROOT = STATE_DIR / "privileged-materialization"
_DEFAULT_INSTANCE_STORAGE_ROOT = Path("/var/lib/capivara-instances")
_DEFAULT_RUNTIME_USER = "capivara-instance"
_AGENT_GROUP = "capivara-agent"


def _token(value: Any) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > 191 or any(ch not in allowed for ch in text):
        raise ValueError("invalid instance_id")
    return text


def _instance_storage_root(config: dict[str, Any]) -> Path:
    raw = str(config.get("instance_storage_root") or _DEFAULT_INSTANCE_STORAGE_ROOT).strip()
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise RuntimeError("Agent instance_storage_root must be an absolute path")
    resolved = path.resolve()
    if resolved == Path("/"):
        raise RuntimeError("Agent instance_storage_root cannot be filesystem root")
    return resolved


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    try:
        account = pwd.getpwnam("capivara-agent")
        os.chown(temp, account.pw_uid, account.pw_gid)
    except (KeyError, OSError):
        pass
    os.replace(temp, path)


def _validate_runtime_user(user: str) -> pwd.struct_passwd:
    try:
        group = grp.getgrnam(_AGENT_GROUP)
    except KeyError as exc:
        raise RuntimeError("capivara-agent group is unavailable") from exc
    try:
        account = pwd.getpwnam(user)
    except KeyError as exc:
        raise RuntimeError(f"runtime user does not exist: {user}") from exc
    if user == _DEFAULT_RUNTIME_USER:
        memberships = set(os.getgrouplist(user, account.pw_gid))
        if group.gr_gid not in memberships:
            raise RuntimeError("capivara-instance is not associated with capivara-agent group")
    return account


def _validate_runtime_access(working_directory: str, user: str) -> None:
    if user != _DEFAULT_RUNTIME_USER:
        return
    state = STATE_DIR.resolve()
    game_data = (STATE_DIR / "game-data").resolve()
    working = Path(working_directory).resolve()
    try:
        working.relative_to(game_data)
    except ValueError:
        return
    if not state.is_dir() or not game_data.is_dir() or not working.is_dir():
        raise RuntimeError("runtime working directory is unavailable")
    state_mode = state.stat().st_mode
    game_data_mode = game_data.stat().st_mode
    if not (state_mode & 0o010):
        raise RuntimeError("Agent state root is not traversable by runtime group")
    if (game_data_mode & 0o050) != 0o050:
        raise RuntimeError("game-data is not readable/traversable by runtime group")


def _within(root: Path, value: str, label: str) -> Path:
    root = root.resolve()
    path = Path(value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{label} escapes its allowed root") from exc
    return path


def _prepare_private_state(spec: dict[str, Any], account: pwd.struct_passwd, storage_root: Path) -> None:
    raw_root = spec.get("instance_state_root")
    if not raw_root:
        return
    expected = (storage_root / spec["instance_id"]).resolve()
    state_root = Path(str(raw_root)).resolve()
    if state_root != expected:
        raise RuntimeError("instance state root does not match Agent instance_storage_root policy")
    storage_root.mkdir(parents=True, exist_ok=True)
    os.chmod(storage_root, 0o711)
    state_root.mkdir(parents=True, exist_ok=True)
    os.chown(state_root, account.pw_uid, account.pw_gid)
    os.chmod(state_root, 0o700)

    working_root = Path(str(spec["working_directory"])).resolve()
    for item in spec.get("writable_directories", []):
        path = _within(state_root, str(item), "writable directory")
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, account.pw_uid, account.pw_gid)
        os.chmod(path, 0o700)

    for item in spec.get("seed_files", []):
        source = _within(working_root, str(item["source"]), "seed source")
        target = _within(state_root, str(item["target"]), "seed target")
        if not source.is_file():
            raise RuntimeError(f"seed source is unavailable: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chown(target.parent, account.pw_uid, account.pw_gid)
        os.chmod(target.parent, 0o700)
        if not target.exists():
            shutil.copy2(source, target)
        os.chown(target, account.pw_uid, account.pw_gid)
        os.chmod(target, 0o600)

    for item in spec.get("bind_paths", []):
        source = _within(state_root, str(item["source"]), "bind source")
        target = _within(working_root, str(item["target"]), "bind target")
        source.mkdir(parents=True, exist_ok=True)
        os.chown(source, account.pw_uid, account.pw_gid)
        os.chmod(source, 0o700)
        target.mkdir(parents=True, exist_ok=True)


def _ensure_runtime_identity(spec: dict[str, Any], config: dict[str, Any]) -> None:
    user = str(spec.get("user") or _DEFAULT_RUNTIME_USER)
    account = _validate_runtime_user(user)
    _validate_runtime_access(str(spec["working_directory"]), user)
    _prepare_private_state(spec, account, _instance_storage_root(config))


def run(instance_id: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("privileged materializer helper must run as root")
    instance_id = _token(instance_id)
    request_path = REQUEST_ROOT / f"{instance_id}.request.json"
    result_path = REQUEST_ROOT / f"{instance_id}.result.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("kind") != "CapivaraPrivilegedMaterializationRequest":
        raise RuntimeError("invalid privileged materialization request")
    if str(request.get("instance_id") or "") != instance_id:
        raise RuntimeError("privileged materialization instance_id mismatch")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    local_agent_id = str(config.get("agent_id") or "").strip()
    if not local_agent_id:
        raise RuntimeError("local Agent identity is unavailable")
    if str(request.get("agent_id") or "") != local_agent_id:
        raise PermissionError("privileged materialization request belongs to another Agent")
    spec = validate_runtime_spec(request.get("spec"), expected_agent_id=local_agent_id)
    if spec["instance_id"] != instance_id:
        raise RuntimeError("runtime spec instance_id mismatch")
    action = str(request.get("action") or "").strip().lower()
    materializer = resolve_materializer(spec)
    templates: list[Any] = []
    if action == "apply":
        _ensure_runtime_identity(spec, config)
        templates = materialize_templates(spec)
        templates.extend(materialize_network_properties(spec))
        operation = materializer.apply(spec)
    elif action == "remove":
        operation = materializer.remove(spec)
    else:
        raise RuntimeError("unsupported privileged materialization action")
    result = {
        "status": "completed",
        "action": action,
        "instance_id": instance_id,
        "agent_id": local_agent_id,
        "operation": operation,
        "templates": templates,
    }
    _write_result(result_path, result)
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: materialize_instance.py INSTANCE_ID", file=sys.stderr)
        return 2
    instance_id = sys.argv[1]
    result_path = REQUEST_ROOT / f"{_token(instance_id)}.result.json"
    try:
        result = run(instance_id)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        _write_result(result_path, {"status": "failed", "instance_id": instance_id, "error": str(exc)[:2000]})
        print(f"privileged materialization failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
