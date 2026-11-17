#!/usr/bin/env python3
"""Isolated Linux bind-mount smoke test for DayZ directory swaps.

Run only on a disposable test host or in an authorized privileged session:
  sudo unshare --mount --propagation private python3 tests/dayz_bind_mount_smoke.py

Never references production DSM paths. All bind mounts and file operations
are confined to a temporary directory inside a private mount namespace.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from server_update_transaction import activate, prepare_staging, rollback


def run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("SKIP: requires root inside an isolated mount namespace")
    # unshare -m supplies a separate namespace; do not risk mounts in the host.
    original_ns = os.readlink("/proc/1/ns/mnt")
    own_ns = os.readlink("/proc/self/ns/mnt")
    if original_ns == own_ns:
        raise SystemExit("REFUSE: not in a separate mount namespace")
    run("mount", "--make-rprivate", "/")
    with tempfile.TemporaryDirectory(prefix="dsm-dayz-bind-smoke-") as td:
        root = Path(td)
        target = root / "game-data" / "serverfiles"
        target.mkdir(parents=True)
        (target / "DayZServer").write_text("old")
        mission_src = root / "private" / "hardcore.namalsk"
        keys_src = root / "private" / "dayz-keys"
        mission_src.mkdir(parents=True)
        keys_src.mkdir(parents=True)
        (mission_src / "mission.sqm").write_text("private mission")
        (keys_src / "server.bikey").write_text("private key")
        mission_dst = target / "mpmissions" / "hardcore.namalsk"
        keys_dst = target / "keys"
        mission_dst.mkdir(parents=True)
        keys_dst.mkdir()
        # Simulate systemd BindPaths during a running instance.
        run("mount", "--bind", str(mission_src), str(mission_dst))
        run("mount", "--bind", str(keys_src), str(keys_dst))
        try:
            assert (mission_dst / "mission.sqm").read_text() == "private mission"
            assert (keys_dst / "server.bikey").read_text() == "private key"
        finally:
            # A stopped systemd unit releases its private bind mounts.
            run("umount", str(keys_dst))
            run("umount", str(mission_dst))
        stage = prepare_staging(target)
        (stage / "DayZServer").write_text("new")
        previous = activate(target, stage)
        assert (target / "DayZServer").read_text() == "new"
        # Simulate systemd recreating BindPaths when restarting the unit.
        run("mount", "--bind", str(mission_src), str(mission_dst))
        run("mount", "--bind", str(keys_src), str(keys_dst))
        try:
            assert (mission_dst / "mission.sqm").read_text() == "private mission"
            assert (keys_dst / "server.bikey").read_text() == "private key"
        finally:
            run("umount", str(keys_dst))
            run("umount", str(mission_dst))
        assert rollback(target, previous)
        assert (target / "DayZServer").read_text() == "old"
        assert (mission_src / "mission.sqm").read_text() == "private mission"
        assert (keys_src / "server.bikey").read_text() == "private key"
    print("PASS: isolated BindPaths activation and rollback")


if __name__ == "__main__":
    main()
