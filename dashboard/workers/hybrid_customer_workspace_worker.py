#!/usr/bin/env python3
"""Fast local command planes for Customer Workspace operations on Hybrid Agents.

The embedded Hybrid Agent shares the Controller database and filesystem. File,
console and binary artifact commands therefore do not need a loopback Agent HTTP
session or synthetic Agent credentials. They reuse the same Agent-owned runtime
executors and Controller repositories as a remote Linux Agent.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

from hybrid_agent_worker import (
    ROOT,
    _database_environment,
    _hybrid_agent_config,
    _instance_runtime_module,
    _read_shell_values,
)
from runtime_backend import backend_from_environment
from artifact_transfer_repository import ArtifactTransferRepository
from instance_file_repository import InstanceFileRepository
from instance_workspace_repository import InstanceWorkspaceRepository

INTERVAL_SECONDS = max(
    1,
    int(os.environ.get("DSM_HYBRID_CUSTOMER_WORKSPACE_SECONDS", "2")),
)
FINAL_STATES = {"completed", "failed"}
_SAFE_TOKEN = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _safe_token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 191
        or text in {".", ".."}
        or any(char not in _SAFE_TOKEN for char in text)
    ):
        raise ValueError(f"invalid {label}")
    return text


def _runtime_client(root: Path, module_name: str):
    _instance_runtime_module(root)
    return importlib.import_module(module_name)


def _owned_instance(root: Path, config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    runtime = _instance_runtime_module(root)
    record = runtime.get_instance(_safe_token(instance_id, "instance_id"))
    if not isinstance(record, dict):
        raise LookupError("instance not found")
    if str(record.get("agent_id") or "") != str(config.get("agent_id") or ""):
        raise PermissionError("instance belongs to another Agent")
    return record


def process_hybrid_file_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    """Consume one Instance File Command with the canonical Linux executor."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {"status": "unavailable", "reason": "config_unavailable"}
    repository = InstanceFileRepository(backend)
    repository.initialize()
    command = repository.command_for_agent(agent_id)
    if not isinstance(command, dict):
        return {"status": "idle"}

    client = _runtime_client(root, "instance_files_client")
    report = client.handle_command(config, command)
    completed = repository.apply_result(agent_id, report)
    status = str((completed or {}).get("status") or report.get("status") or "unknown").lower()
    if status in FINAL_STATES:
        client.clear_result(str(command.get("command_id") or ""))
    return {
        "status": status,
        "command_id": command.get("command_id"),
        "instance_id": command.get("instance_id"),
        "action": command.get("action"),
    }


def process_hybrid_console_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    """Consume one game-console command using the runtime-declared transport."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {"status": "unavailable", "reason": "config_unavailable"}
    repository = InstanceWorkspaceRepository(backend)
    repository.initialize()
    command = repository.command_for_agent(agent_id)
    if not isinstance(command, dict):
        return {"status": "idle"}

    command_id = _safe_token(command.get("command_id"), "console command_id")
    repository.mark_console_delivered(command_id)
    client = _runtime_client(root, "console_client")
    report = client.handle_command(config, command)
    completed = repository.apply_console_result(agent_id, report)
    status = str((completed or {}).get("status") or report.get("status") or "unknown").lower()
    if status in FINAL_STATES:
        client.clear_result(command_id)
    return {
        "status": status,
        "command_id": command_id,
        "instance_id": command.get("instance_id"),
    }


def _backup_root(root: Path) -> Path:
    client = _runtime_client(root, "backup_client")
    value = Path(client.BACKUP_ROOT).resolve()
    state_root = (root / "runtime" / "hybrid-agent-state").resolve()
    value.relative_to(state_root)
    return value


def _backup_directory(root: Path, config: dict[str, Any], instance_id: str) -> Path:
    _owned_instance(root, config, instance_id)
    base = _backup_root(root)
    directory = (base / _safe_token(instance_id, "instance_id")).resolve()
    directory.relative_to(base)
    return directory


def _backup_artifact(
    root: Path,
    config: dict[str, Any],
    instance_id: str,
    backup_id: str,
) -> Path:
    directory = _backup_directory(root, config, instance_id)
    backup_id = _safe_token(backup_id, "backup_id")
    matches = [
        path
        for path in directory.glob(f"{backup_id}.tar*")
        if path.is_file() and not path.is_symlink()
    ]
    if len(matches) != 1:
        raise FileNotFoundError("backup artifact not found")
    artifact = matches[0].resolve()
    artifact.relative_to(directory)
    return artifact


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _import_suffix(filename: str) -> str:
    name = str(filename or "").lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return ".tar.gz"
    if name.endswith(".tar"):
        return ".tar"
    raise ValueError("unsupported backup archive")


def _install_controller_artifact(
    repository: ArtifactTransferRepository,
    item: dict[str, Any],
    root: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    transfer_id = _safe_token(item.get("transfer_id"), "transfer_id")
    instance_id = _safe_token(item.get("instance_id"), "instance_id")
    backup_id = _safe_token(item.get("destination_ref"), "backup_id")
    source, fresh = repository.controller_artifact(transfer_id)
    expected_size = int(fresh.get("size_bytes") or source.stat().st_size)
    expected_sha = str(fresh.get("sha256") or "").strip().lower()
    directory = _backup_directory(root, config, instance_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = (directory / f"{backup_id}{_import_suffix(str(fresh.get('filename') or ''))}").resolve()
    destination.relative_to(directory)
    if destination.is_symlink():
        raise ValueError("backup destination cannot be a symbolic link")

    if destination.exists():
        if not destination.is_file():
            raise ValueError("backup destination is not a file")
        size = destination.stat().st_size
        digest = _digest(destination)
        if size != expected_size or (expected_sha and digest != expected_sha):
            raise FileExistsError("backup destination already exists with different content")
        return {"size_bytes": size, "sha256": digest, "artifact_path": str(destination)}

    temp = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as incoming, temp.open("xb") as outgoing:
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                total += len(chunk)
                digest.update(chunk)
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        os.chmod(temp, 0o600)
        actual_sha = digest.hexdigest()
        if total != expected_size:
            raise ValueError("artifact size mismatch")
        if expected_sha and actual_sha != expected_sha:
            raise ValueError("artifact sha256 mismatch")
        os.replace(temp, destination)
        return {"size_bytes": total, "sha256": actual_sha, "artifact_path": str(destination)}
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def process_hybrid_artifact_cycle(backend, root: Path, agent_id: str) -> dict[str, Any]:
    """Bridge one Artifact Transfer locally without Agent HTTP credentials."""
    config = _hybrid_agent_config(root, agent_id, optional=True)
    if config is None:
        return {"status": "unavailable", "reason": "config_unavailable"}
    repository = ArtifactTransferRepository(backend, root)
    repository.initialize()
    command = repository.command_for_agent(agent_id)
    if not isinstance(command, dict):
        return {"status": "idle"}

    transfer_id = _safe_token(command.get("transfer_id"), "transfer_id")
    direction = str(command.get("direction") or "")
    repository.mark_transferring(transfer_id)
    try:
        if direction == "agent_to_controller":
            source = _backup_artifact(
                root,
                config,
                str(command.get("instance_id") or ""),
                str(command.get("source_ref") or ""),
            )
            with source.open("rb") as handle:
                completed = repository.receive_from_agent(
                    transfer_id,
                    agent_id,
                    handle,
                    content_length=source.stat().st_size,
                )
        elif direction == "controller_to_agent":
            detail = _install_controller_artifact(repository, command, root, config)
            completed = repository.apply_agent_result(
                agent_id,
                {
                    "transfer_id": transfer_id,
                    "status": "completed",
                    "transferred_bytes": detail["size_bytes"],
                },
            )
        else:
            raise ValueError("unsupported artifact transfer direction")
    except Exception as exc:
        try:
            completed = repository.apply_agent_result(
                agent_id,
                {
                    "transfer_id": transfer_id,
                    "status": "failed",
                    "error": str(exc)[:1024],
                },
            )
        except Exception:
            raise exc

    return {
        "status": str((completed or {}).get("status") or "unknown").lower(),
        "transfer_id": transfer_id,
        "instance_id": command.get("instance_id"),
        "direction": direction,
    }


def workspace_cycle(root: Path = ROOT, *, backend=None) -> dict[str, Any]:
    config = _read_shell_values(root / "config" / "agent.conf")
    if str(config.get("DSM_NODE_ROLE", "")).strip().lower() != "hybrid":
        return {"active": False, "reason": "not_hybrid"}
    agent_id = str(config.get("AGENT_ID", "")).strip()
    if not agent_id:
        return {"active": False, "reason": "identity_incomplete"}

    effective_backend = backend or backend_from_environment(_database_environment(root))
    return {
        "active": True,
        "agent_id": agent_id,
        "file": process_hybrid_file_cycle(effective_backend, root, agent_id),
        "console": process_hybrid_console_cycle(effective_backend, root, agent_id),
        "artifact": process_hybrid_artifact_cycle(effective_backend, root, agent_id),
    }


def run_forever(root: Path = ROOT) -> None:
    while True:
        try:
            result = workspace_cycle(root)
            if result.get("active"):
                print(
                    "hybrid customer workspace ok "
                    f"agent={result.get('agent_id')} "
                    f"file={(result.get('file') or {}).get('status', 'idle')} "
                    f"console={(result.get('console') or {}).get('status', 'idle')} "
                    f"artifact={(result.get('artifact') or {}).get('status', 'idle')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"hybrid customer workspace failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL_SECONDS)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "once":
        print(workspace_cycle(ROOT))
        return 0
    run_forever(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
