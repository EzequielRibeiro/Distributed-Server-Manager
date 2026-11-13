#!/usr/bin/env python3
"""Read-only systemd unit observation of version-pinned Minecraft supervisor.

Does not rewrite units or grant live update permission.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import shlex
from typing import Callable, Mapping, Any

_SHA = re.compile(r"^[a-f0-9]{64}$")
class SupervisorUnitError(ValueError):
    pass

def verify_pinned_supervisor(unit: str, *, versions_dir: Path, expected_sha256: str,
                             inspect: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    if not _SHA.fullmatch(expected_sha256):
        raise SupervisorUnitError("invalid digest")
    if not isinstance(unit, str) or not re.fullmatch(r"capivara-instance-[A-Za-z0-9_.-]+\.service", unit):
        raise SupervisorUnitError("invalid unit")
    if versions_dir.is_symlink() or not versions_dir.is_dir():
        raise SupervisorUnitError("unsafe versions directory")
    expected = versions_dir / ("console-supervisor-" + expected_sha256 + ".py")
    if expected.is_symlink() or not expected.is_file():
        raise SupervisorUnitError("missing or unsafe versioned supervisor")
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
    return {"kind": "CapivaraMinecraftPinnedSupervisorObservation", "unit": unit,
            "sha256": expected_sha256, "main_pid": pid, "start_stamp": stamp,
            "systemd_pinned_observed": True, "live_no_drain_authorized": False}
