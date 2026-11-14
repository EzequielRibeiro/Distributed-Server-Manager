#!/usr/bin/env python3
"""Prepare an immutable-by-policy, versioned Minecraft supervisor copy offline.

This stages a *candidate* outside the replaceable release tree. It never
changes systemd units, running processes or the updater, and cannot by itself
prove that the service's ExecStart uses the staged copy.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

_SHA = re.compile(r"^[a-f0-9]{64}$")


class SupervisorIsolationError(ValueError):
    pass


def _regular(path: Path) -> os.stat_result:
    if path.is_symlink():
        raise SupervisorIsolationError("symlink refused")
    try:
        info = path.stat()
    except OSError as exc:
        raise SupervisorIsolationError("unreadable path") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SupervisorIsolationError("unsafe supervisor file")
    return info


def stage_supervisor(source: Path, versions: Path, *, expected_sha256: str) -> dict:
    """Safely stage under a caller-provided private, pre-created directory.

    The caller must independently provision versions outside the updater
    replacement set and prove service ownership and lifecycle compatibility.
    """
    if not _SHA.fullmatch(expected_sha256):
        raise SupervisorIsolationError("invalid expected digest")
    if versions.is_symlink() or not versions.is_dir():
        raise SupervisorIsolationError("unsafe versions directory")
    parent = versions.stat()
    if parent.st_uid != os.geteuid() or (parent.st_mode & 0o022):
        raise SupervisorIsolationError("versions directory writable by other users")
    src_stat = _regular(source)
    if src_stat.st_size > 1024 * 1024:
        raise SupervisorIsolationError("supervisor exceeds bounded size")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SupervisorIsolationError("source digest mismatch")
    if _regular(source).st_ino != src_stat.st_ino:
        raise SupervisorIsolationError("source changed during read")
    name = "console-supervisor-" + expected_sha256 + ".py"
    dest = versions / name
    if dest.is_symlink():
        raise SupervisorIsolationError("destination symlink")
    if dest.exists():
        _regular(dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest() != expected_sha256:
            raise SupervisorIsolationError("existing version is corrupt")
        return {"path": str(dest), "sha256": expected_sha256, "already_present": True,
                "systemd_integrated": False, "live_no_drain_authorized": False}
    fd, tmp_name = tempfile.mkstemp(prefix=".supervisor-", dir=versions)
    try:
        with os.fdopen(fd, "wb") as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(tmp_name, 0o444)
        # No overwrite: another writer racing this operation must fail closed.
        os.link(tmp_name, dest, follow_symlinks=False)
        directory_fd = os.open(versions, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise SupervisorIsolationError("concurrent supervisor publication") from exc
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return {"path": str(dest), "sha256": expected_sha256, "already_present": False,
            "systemd_integrated": False, "live_no_drain_authorized": False}
