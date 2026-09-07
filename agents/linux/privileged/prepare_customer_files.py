#!/usr/bin/env python3
"""Root-owned helper that exposes only a runtime's customer-manageable files tree to the Agent group."""
from __future__ import annotations

import grp
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
RUNTIME_DIR = INSTALL_ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import instance_runtime

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
_AGENT_GROUP = "capivara-agent"


def _token(value: Any, label: str = "instance_id", max_length: int = 191) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > max_length or any(ch not in allowed for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def _owned_record(config: dict[str, Any], instance_id: str) -> dict[str, Any]:
    record = instance_runtime.get_instance(instance_id)
    if not isinstance(record, dict):
        raise LookupError("instance not found")
    if str(record.get("agent_id") or "") != str(config.get("agent_id") or ""):
        raise PermissionError("instance belongs to another Agent")
    return record


def _managed_root(record: dict[str, Any]) -> tuple[Path, Path]:
    raw_state = str(record.get("instance_state_root") or "").strip()
    raw_files = str(record.get("files_root") or "").strip()
    if not raw_state or not raw_files:
        raise RuntimeError("customer files root is not declared")
    state_root = Path(raw_state)
    files_root = Path(raw_files)
    if not state_root.is_absolute() or not files_root.is_absolute():
        raise RuntimeError("customer files paths must be absolute")
    state_root = state_root.resolve()
    files_root = files_root.resolve()
    try:
        files_root.relative_to(state_root)
    except ValueError as exc:
        raise RuntimeError("customer files root escapes private instance state") from exc
    if not files_root.is_dir() or files_root.is_symlink():
        raise RuntimeError("customer files root is unavailable")
    return state_root, files_root


def _prepare_tree(root: Path, group_gid: int) -> dict[str, int]:
    directories = 0
    files = 0
    stack = [root]
    while stack:
        current = stack.pop()
        if current.is_symlink():
            raise RuntimeError(f"customer files tree contains a symlink: {current}")
        if current.is_dir():
            os.chown(current, -1, group_gid)
            os.chmod(current, 0o770)
            directories += 1
            stack.extend(current.iterdir())
            continue
        if current.is_file():
            os.chown(current, -1, group_gid)
            os.chmod(current, 0o660)
            files += 1
    return {"directories": directories, "files": files}


def run(instance_id: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("customer files access helper must run as root")
    instance_id = _token(instance_id)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RuntimeError("Agent config must be a JSON object")
    record = _owned_record(config, instance_id)
    _, files_root = _managed_root(record)
    try:
        group = grp.getgrnam(_AGENT_GROUP)
    except KeyError as exc:
        raise RuntimeError("capivara-agent group is unavailable") from exc
    counts = _prepare_tree(files_root, group.gr_gid)
    return {
        "instance_id": instance_id,
        "files_root": str(files_root),
        "group": _AGENT_GROUP,
        "directory_mode": "0770",
        "file_mode": "0660",
        **counts,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: prepare_customer_files.py INSTANCE_ID", file=sys.stderr)
        return 2
    try:
        result = run(args[0])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
