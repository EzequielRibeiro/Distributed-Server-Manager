#!/usr/bin/env python3
"""Read-only systemd unit observation of version-pinned Minecraft supervisor.

Does not rewrite units or grant live update permission.
"""
from __future__ import annotations
import hashlib
import os
import stat
from pathlib import Path
import re
import shlex
from typing import Callable, Mapping, Any

_SHA = re.compile(r"^[a-f0-9]{64}$")
class SupervisorUnitError(ValueError):
    pass

def _running_command(pid: int) -> tuple[list[str], int]:
    """Read actual kernel process identity, not a reloaded unit's future argv."""
    root = Path("/proc") / str(pid)
    def stamp():
        raw = (root / "stat").read_text()
        return int(raw.rsplit(")", 1)[1].split()[19])
    try:
        start = stamp()
        with (root / "cmdline").open("rb") as stream:
            raw = stream.read(65537)
        if not 0 < len(raw) <= 65536 or not raw.endswith(b"\x00") or stamp() != start:
            raise SupervisorUnitError("running supervisor process changed")
        return [part.decode("utf-8") for part in raw[:-1].split(b"\x00")], start
    except (OSError, ValueError, UnicodeError, IndexError) as exc:
        raise SupervisorUnitError("running supervisor process unverifiable") from exc


def verify_pinned_supervisor(unit: str, *, versions_dir: Path, expected_sha256: str,
                             inspect: Callable[[str], Mapping[str, Any]],
                             require_live_process: bool = False) -> dict[str, Any]:
    if not _SHA.fullmatch(expected_sha256):
        raise SupervisorUnitError("invalid digest")
    if not isinstance(unit, str) or not re.fullmatch(r"capivara-instance-[A-Za-z0-9_.-]+\.service", unit):
        raise SupervisorUnitError("invalid unit")
    if versions_dir.is_symlink() or not versions_dir.is_dir():
        raise SupervisorUnitError("unsafe versions directory")
    expected = versions_dir / ("console-supervisor-" + expected_sha256 + ".py")
    if expected.is_symlink() or not expected.is_file():
        raise SupervisorUnitError("missing or unsafe versioned supervisor")
    # A digest alone does not pin the executable: mutable files or hardlinks
    # can be replaced after inspection while the unit still names this path.
    directory = versions_dir.stat()
    info = expected.stat()
    if (directory.st_uid != os.geteuid() or directory.st_mode & 0o022 or
            not stat.S_ISDIR(directory.st_mode)):
        raise SupervisorUnitError("unsafe version directory ownership or permissions")
    if (info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode) or
            info.st_nlink != 1 or info.st_mode & 0o222 or
            info.st_size <= 0 or info.st_size > 1024 * 1024):
        raise SupervisorUnitError("unsafe mutable or linked supervisor")
    if hashlib.sha256(expected.read_bytes()).hexdigest() != expected_sha256:
        raise SupervisorUnitError("supervisor hash mismatch")
    try:
        observed = inspect(unit)
        pid, stamp = observed["main_pid"], observed["start_stamp"]
        command, fragment = observed["exec"], observed["fragment"]
    except (KeyError, TypeError) as exc:
        raise SupervisorUnitError("incomplete systemd evidence") from exc
    if type(pid) is not int or pid <= 1 or type(stamp) is not int or stamp <= 0:
        raise SupervisorUnitError("invalid process identity")
    if not isinstance(fragment, str) or not fragment.startswith("/etc/systemd/system/"):
        raise SupervisorUnitError("untrusted unit fragment")
    if not isinstance(command, str):
        raise SupervisorUnitError("invalid ExecStart")
    match = re.search(r"(?:^|\s)argv\[\]=([^;]+);", command)
    if match is None:
        raise SupervisorUnitError("unrecognized systemd ExecStart format")
    try:
        args = shlex.split(match.group(1).strip())
    except ValueError as exc:
        raise SupervisorUnitError("malformed ExecStart") from exc
    if args.count(str(expected)) != 1 or "--socket" not in args:
        raise SupervisorUnitError("pinned supervisor not invoked")
    if any("/opt/dsm/agents/" in arg for arg in args):
        raise SupervisorUnitError("replaceable agent path in ExecStart")
    if any(arg.endswith("console_supervisor.py") and arg != str(expected) for arg in args):
        raise SupervisorUnitError("replaceable supervisor reference")
    if require_live_process:
        running, ticks = _running_command(pid)
        if running != args:
            raise SupervisorUnitError("running supervisor is not the configured pinned revision")
        after = inspect(unit)
        if any(after.get(key) != observed.get(key) for key in
               ("main_pid", "start_stamp", "exec", "fragment", "unit_config_sha256")):
            raise SupervisorUnitError("supervisor identity changed during live inspection")
        if _running_command(pid) != (running, ticks):
            raise SupervisorUnitError("running supervisor identity changed")
    return {"kind": "CapivaraMinecraftPinnedSupervisorObservation", "unit": unit,
            "sha256": expected_sha256, "main_pid": pid, "start_stamp": stamp,
            "systemd_pinned_observed": True, "live_no_drain_authorized": False}
