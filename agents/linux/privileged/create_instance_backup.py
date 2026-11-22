#!/usr/bin/env python3
"""Constrained root helper for backing up protected external instance trees.

The unprivileged Agent remains the only Controller endpoint.  The helper
accepts one fixed action and one validated local instance, never arbitrary
systemd units, source directories, output paths or shell commands.
"""
from __future__ import annotations

import json
import os
import pwd
import grp
import stat
import sys
from pathlib import Path
from typing import Any

INSTALL_ROOT = Path(os.environ.get("CAPIVARA_AGENT_ROOT", "/opt/capivara-agent"))
RUNTIME = INSTALL_ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))
if str(INSTALL_ROOT / "privileged") not in sys.path:
    sys.path.insert(0, str(INSTALL_ROOT / "privileged"))

import backup_client
from game_uptime_privileged_admission import (
    fence_privileged_helper_run, require_privileged_mutation_admission,
)
from restore_instance_backup import (
    _token, _write_result, _validate_external_target,
)

STATE = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
REQUEST_ROOT = STATE / "privileged-backup-create"
EXPECTED_BACKUPS = STATE / "backups"


@fence_privileged_helper_run
def run(command_id: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("privileged backup creator must run as root")
    require_privileged_mutation_admission()
    if os.environ.get("CAPIVARA_AGENT_MODE") == "hybrid":
        raise PermissionError("external backup creator does not support hybrid pools")
    command_id = _token(command_id, "command_id")
    request_path = REQUEST_ROOT / f"{command_id}.request.json"
    result_path = REQUEST_ROOT / f"{command_id}.result.json"
    if request_path.is_symlink() or REQUEST_ROOT.is_symlink():
        raise PermissionError("unsafe privileged backup request")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("kind") != "CapivaraPrivilegedBackupCreateRequest":
        raise ValueError("invalid privileged backup create request")
    if request.get("command_id") != command_id or request.get("action") != "create":
        raise ValueError("privileged backup create command mismatch")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RuntimeError("invalid local Agent config")
    agent_id = _token(config.get("agent_id"), "agent_id")
    if str(request.get("agent_id") or "") != agent_id:
        raise PermissionError("privileged backup create belongs to another Agent")
    instance_id = _token(request.get("instance_id"), "instance_id")
    _validate_external_target(config, instance_id)
    record, root = backup_client._owned(config, instance_id)
    expected = Path("/var/lib/capivara-instances") / instance_id
    if root != expected or root.is_symlink():
        raise PermissionError("unsafe backup source boundary")
    owner = pwd.getpwnam("capivara-instance")
    group = grp.getgrnam("capivara-agent")
    st = root.stat()
    if (st.st_uid != owner.pw_uid or st.st_gid != group.gr_gid
            or stat.S_IMODE(st.st_mode) not in (0o700, 0o710)):
        raise PermissionError("protected instance ownership or root permissions differ")
    if backup_client.BACKUP_ROOT != EXPECTED_BACKUPS.resolve():
        raise PermissionError("noncanonical backup destination")
    if EXPECTED_BACKUPS.is_symlink():
        raise PermissionError("backup root is a symlink")

    policy = request.get("policy")
    if not isinstance(policy, dict) or str(policy.get("consistency") or "live") != "live":
        raise ValueError("privileged backup requires live consistency")
    for key in ("include_paths", "exclude_paths"):
        values = policy.get(key) or []
        if not isinstance(values, list) or len(values) > 256 or any(
            not isinstance(v, str) or len(v) > 1024 for v in values
        ):
            raise ValueError("invalid privileged backup path selection")

    operation = backup_client._create(config, {
        "command_id": command_id,
        "instance_id": instance_id,
        "action": "create",
        "policy": policy,
    })
    archive = Path(str(operation.get("artifact_path") or ""))
    expected_parent = EXPECTED_BACKUPS / instance_id
    if (archive.is_symlink() or not archive.is_file()
            or archive.parent != expected_parent or not archive.name.endswith((".tar", ".tar.gz"))):
        raise PermissionError("unexpected privileged backup artifact")
    # The helper reads the protected tree but must return the archive to the
    # unprivileged Agent's custody for verification, inventory and download.
    agent = pwd.getpwnam("capivara-agent")
    os.chown(archive, agent.pw_uid, agent.pw_gid, follow_symlinks=False)
    os.chmod(archive, 0o600)

    result = {
        "status": "completed",
        "action": "create",
        "command_id": command_id,
        "instance_id": instance_id,
        "agent_id": agent_id,
        "operation": operation,
    }
    _write_result(result_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: create_instance_backup.py COMMAND_ID", file=sys.stderr)
        return 2
    try:
        command_id = _token(args[0], "command_id")
    except Exception as exc:
        print(f"privileged backup create: {exc}", file=sys.stderr)
        return 1
    try:
        result = run(command_id)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        _write_result(REQUEST_ROOT / f"{command_id}.result.json", {
            "status": "failed", "command_id": command_id,
            "error": str(exc)[:2000],
        })
        print(f"privileged backup create failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
