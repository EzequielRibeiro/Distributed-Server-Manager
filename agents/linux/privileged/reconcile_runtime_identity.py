#!/usr/bin/env python3
"""Reconcile privileged Linux runtime identity and canonical host identity state."""
from __future__ import annotations

import grp
import hashlib
import os
import pwd
import stat
import subprocess
from pathlib import Path

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RUNTIME_USER = "capivara-instance"
AGENT_GROUP = "capivara-agent"
RUNTIME_HOME = STATE_DIR / "runtime-home"
HOST_IDENTITY_PATH = STATE_DIR / "host-identity"


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"command failed: {' '.join(command)}")[:2000])


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return ""


def _canonical_host_identity() -> str:
    """Return a stable host identity from privileged host identifiers."""
    machine_id = _read_text(Path("/etc/machine-id"))
    product_uuid = _read_text(Path("/sys/class/dmi/id/product_uuid"))

    macs: list[str] = []
    try:
        interfaces = Path("/sys/class/net").iterdir()
    except OSError:
        interfaces = ()

    for interface in interfaces:
        if interface.name == "lo":
            continue
        value = _read_text(interface / "address")
        if value and value != "00:00:00:00:00:00":
            macs.append(value)

    hardware_identity = product_uuid or "|".join(sorted(set(macs)))
    if not machine_id or not hardware_identity:
        raise RuntimeError("stable host identity inputs are unavailable")

    material = "\n".join([
        "capivara-host-v1",
        machine_id,
        hardware_identity,
    ]).encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _write_canonical_host_identity(group_gid: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    identity = _canonical_host_identity()
    temporary = HOST_IDENTITY_PATH.with_name(HOST_IDENTITY_PATH.name + ".tmp")
    temporary.write_text(identity + "\n", encoding="utf-8")
    os.chown(temporary, 0, group_gid)
    os.chmod(temporary, 0o640)
    os.replace(temporary, HOST_IDENTITY_PATH)
    os.chown(HOST_IDENTITY_PATH, 0, group_gid)
    os.chmod(HOST_IDENTITY_PATH, 0o640)


def reconcile() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("runtime identity reconciliation must run as root")
    try:
        group = grp.getgrnam(AGENT_GROUP)
    except KeyError as exc:
        raise RuntimeError("capivara-agent group is unavailable") from exc

    runtime_home = str(RUNTIME_HOME)
    try:
        account = pwd.getpwnam(RUNTIME_USER)
    except KeyError:
        _run([
            "useradd", "--system", "--gid", AGENT_GROUP,
            "--home-dir", runtime_home, "--no-create-home",
            "--shell", "/usr/sbin/nologin", RUNTIME_USER,
        ])
        account = pwd.getpwnam(RUNTIME_USER)

    if account.pw_dir != runtime_home:
        _run(["usermod", "--home", runtime_home, RUNTIME_USER])
        account = pwd.getpwnam(RUNTIME_USER)

    memberships = set(os.getgrouplist(RUNTIME_USER, account.pw_gid))
    if group.gr_gid not in memberships:
        _run(["usermod", "-a", "-G", AGENT_GROUP, RUNTIME_USER])

    # Stable mountpoint for per-instance private homes. It stays root-owned outside
    # instance units; systemd bind-mounts each unit's StateDirectory over it.
    RUNTIME_HOME.mkdir(parents=True, exist_ok=True)
    os.chown(RUNTIME_HOME, 0, group.gr_gid)
    os.chmod(RUNTIME_HOME, 0o755)

    game_data = STATE_DIR / "game-data"
    if STATE_DIR.is_dir():
        os.chown(STATE_DIR, -1, group.gr_gid)
        os.chmod(STATE_DIR, stat.S_IMODE(STATE_DIR.stat().st_mode) | stat.S_IXGRP)
    if game_data.is_dir():
        os.chown(game_data, -1, group.gr_gid)
        os.chmod(game_data, stat.S_IMODE(game_data.stat().st_mode) | stat.S_IRGRP | stat.S_IXGRP)

    _write_canonical_host_identity(group.gr_gid)


if __name__ == "__main__":
    reconcile()
