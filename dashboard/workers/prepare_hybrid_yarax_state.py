#!/usr/bin/env python3
"""Prepare ownership for the embedded Hybrid YARA-X managed-state subtree."""
from __future__ import annotations

import argparse
import grp
import os
import pwd
from pathlib import Path


def _bounded_state_root(root: Path) -> Path:
    root = root.resolve()
    target = (root / "runtime" / "hybrid-agent-state" / "security" / "yara-x").resolve()
    target.relative_to(root)
    return target


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)
    for current, directories, files in os.walk(path, followlinks=False):
        base = Path(current)
        for name in directories:
            child = base / name
            if child.is_symlink():
                continue
            os.chown(child, uid, gid, follow_symlinks=False)
        for name in files:
            child = base / name
            if child.is_symlink():
                continue
            os.chown(child, uid, gid, follow_symlinks=False)


def prepare(root: Path, user: str, group: str) -> Path:
    target = _bounded_state_root(root)
    uid = pwd.getpwnam(user).pw_uid
    gid = grp.getgrnam(group).gr_gid
    target.mkdir(parents=True, mode=0o750, exist_ok=True)
    target.chmod(0o750)
    _chown_tree(target, uid, gid)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    args = parser.parse_args()
    prepare(Path(args.root), args.user, args.group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
