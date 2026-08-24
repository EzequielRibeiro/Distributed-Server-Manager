#!/usr/bin/env python3
"""Reconcile the fixed Linux instance-runtime identity outside the materializer sandbox."""
from __future__ import annotations

import grp
import os
import pwd
import stat
import subprocess
from pathlib import Path

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
RUNTIME_USER = "capivara-instance"
AGENT_GROUP = "capivara-agent"


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"command failed: {' '.join(command)}")[:2000])


def reconcile() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("runtime identity reconciliation must run as root")
    try:
        group = grp.getgrnam(AGENT_GROUP)
    except KeyError as exc:
        raise RuntimeError("capivara-agent group is unavailable") from exc

    try:
        account = pwd.getpwnam(RUNTIME_USER)
    except KeyError:
        _run([
            "useradd", "--system", "--gid", AGENT_GROUP,
            "--home-dir", "/nonexistent", "--no-create-home",
            "--shell", "/usr/sbin/nologin", RUNTIME_USER,
        ])
        account = pwd.getpwnam(RUNTIME_USER)

    memberships = set(os.getgrouplist(RUNTIME_USER, account.pw_gid))
    if group.gr_gid not in memberships:
        _run(["usermod", "-a", "-G", AGENT_GROUP, RUNTIME_USER])

    game_data = STATE_DIR / "game-data"
    if STATE_DIR.is_dir():
        os.chown(STATE_DIR, -1, group.gr_gid)
        os.chmod(STATE_DIR, stat.S_IMODE(STATE_DIR.stat().st_mode) | stat.S_IXGRP)
    if game_data.is_dir():
        os.chown(game_data, -1, group.gr_gid)
        os.chmod(game_data, stat.S_IMODE(game_data.stat().st_mode) | stat.S_IRGRP | stat.S_IXGRP)


if __name__ == "__main__":
    reconcile()
