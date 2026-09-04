#!/usr/bin/env python3
"""Root-owned helper that applies/removes only validated Capivara instance runtimes."""
from __future__ import annotations

import grp
import hashlib
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
from storage_pools import resolve_storage_pool

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
REQUEST_ROOT = STATE_DIR / "privileged-materialization"
_DEFAULT_RUNTIME_USER = "capivara-instance"
_AGENT_GROUP = "capivara-agent"
_FORBIDDEN_STORAGE_ROOTS = tuple(Path(value) for value in ("/boot", "/dev", "/etc", "/proc", "/root", "/run", "/sys", "/usr"))


def _token(value: Any, label: str = "instance_id", max_length: int = 191) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > max_length or any(ch not in allowed for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def _storage_root(value: Any, label: str) -> Path:
    raw = str(value or "").strip()
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise RuntimeError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"):
        raise RuntimeError(f"{label} cannot be filesystem root")
    for forbidden in _FORBIDDEN_STORAGE_ROOTS:
        try:
            resolved.relative_to(forbidden)
        except ValueError:
            continue
        raise RuntimeError(f"{label} is inside a protected system path")
    return resolved


def _instance_storage_root(config: dict[str, Any], storage_pool_id: str | None = None) -> Path:
    try:
        pool = resolve_storage_pool(config, storage_pool_id)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return _storage_root(pool["root_path"], f"Agent storage pool {pool['id']} root")


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    try:
        account = pwd.getpwnam(os.environ.get("CAPIVARA_AGENT_RESULT_USER", "capivara-agent"))
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
    if not (state.stat().st_mode & 0o010):
        raise RuntimeError("Agent state root is not traversable by runtime group")
    if (game_data.stat().st_mode & 0o050) != 0o050:
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
        raise RuntimeError("instance state root does not match Agent storage pool policy")
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
    _prepare_private_state(spec, account, _instance_storage_root(config, spec.get("storage_pool_id")))


def _reject_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeError("storage migration source root cannot be a symlink")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"storage migration refuses symlink: {path.relative_to(root)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_tree(source: Path, target: Path) -> tuple[int, int]:
    _reject_symlinks(source)
    _reject_symlinks(target)
    source_files = {p.relative_to(source): p for p in source.rglob("*") if p.is_file()}
    target_files = {p.relative_to(target): p for p in target.rglob("*") if p.is_file()}
    if source_files.keys() != target_files.keys():
        raise RuntimeError("storage migration verification failed: file set differs")
    total = 0
    for relative, src in source_files.items():
        dst = target_files[relative]
        if src.stat().st_size != dst.stat().st_size or _sha256(src) != _sha256(dst):
            raise RuntimeError(f"storage migration verification failed: {relative}")
        total += src.stat().st_size
    return len(source_files), total


def _migrate_storage_copy(
    config: dict[str, Any],
    spec: dict[str, Any],
    *,
    target_storage_pool_id: Any = None,
    migration_id: Any = None,
    target_root_value: Any = None,
) -> dict[str, Any]:
    source_pool_id = str(spec.get("storage_pool_id") or "").strip() or None
    source_root = _instance_storage_root(config, source_pool_id)
    if target_storage_pool_id is not None:
        target_pool_id = _token(target_storage_pool_id, "target_storage_pool_id", 64)
        target_root = _instance_storage_root(config, target_pool_id)
        migration_token = _token(migration_id, "migration_id")
    else:
        target_pool_id = None
        target_root = _storage_root(target_root_value, "target storage root")
        migration_token = "root-migration"

    if source_root == target_root:
        return {
            "changed": False,
            "source_storage_pool_id": source_pool_id,
            "target_storage_pool_id": target_pool_id,
            "source": str(source_root),
            "target": str(target_root),
            "verified_files": 0,
            "verified_bytes": 0,
            "source_preserved": True,
        }

    instance_id = spec["instance_id"]
    source = (source_root / instance_id).resolve(strict=False)
    expected = Path(str(spec.get("instance_state_root") or source)).resolve(strict=False)
    if source != expected:
        raise RuntimeError("instance source state root does not match current Agent storage pool")
    final = (target_root / instance_id).resolve(strict=False)
    final.relative_to(target_root)
    staging = (target_root / f".capivara-migrate-{instance_id}-{migration_token}").resolve(strict=False)
    staging.relative_to(target_root)
    if final.exists():
        raise RuntimeError("target instance state already exists")
    if staging.exists():
        shutil.rmtree(staging)
    target_root.mkdir(parents=True, exist_ok=True)
    os.chmod(target_root, 0o711)

    try:
        if source.exists():
            _reject_symlinks(source)
            shutil.copytree(source, staging, copy_function=shutil.copy2, symlinks=False)
            count, total = _verify_tree(source, staging)
        else:
            staging.mkdir(parents=True, exist_ok=False)
            count, total = 0, 0
        account = _validate_runtime_user(str(spec.get("user") or _DEFAULT_RUNTIME_USER))
        os.chown(staging, account.pw_uid, account.pw_gid)
        os.chmod(staging, 0o700)
        os.replace(staging, final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "changed": True,
        "source_storage_pool_id": source_pool_id,
        "target_storage_pool_id": target_pool_id,
        "source": str(source),
        "target": str(final),
        "verified_files": count,
        "verified_bytes": total,
        "source_preserved": True,
        "atomic_commit": True,
    }


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
    elif action == "migrate-storage-copy":
        operation = _migrate_storage_copy(
            config,
            spec,
            target_storage_pool_id=request.get("target_storage_pool_id"),
            migration_id=request.get("migration_id"),
            target_root_value=request.get("target_root"),
        )
    else:
        raise RuntimeError("unsupported privileged materialization action")
    result = {"status": "completed", "action": action, "instance_id": instance_id,
              "agent_id": local_agent_id, "operation": operation, "templates": templates}
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
