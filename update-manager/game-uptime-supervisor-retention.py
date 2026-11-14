#!/usr/bin/env python3
"""Fail-closed *read-only* retention planning for versioned game supervisors.

Protect every existing valid version by default. A caller must supply an
exhaustive inventory of managed unit files AND running process identities;
neither this tool nor a passed-in record authorizes deletion or live updates.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shlex
import stat
from typing import Any, Mapping

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"console-supervisor-([0-9a-f]{64})\.py\Z")
_UNIT = re.compile(r"capivara-instance-[A-Za-z0-9._-]+\.service\Z")


def _pin_from_unit(content: str, directory: Path) -> str | None:
    """Read exactly one pinned supervisor from a rendered systemd ExecStart."""
    if not isinstance(content, str):
        raise ValueError("invalid systemd unit content")
    commands = [
        line.split("=", 1)[1] for line in content.splitlines()
        if line.startswith("ExecStart=")
    ]
    if len(commands) != 1:
        raise ValueError("expected exactly one ExecStart")
    try:
        arguments = shlex.split(commands[0])
    except ValueError as exc:
        raise ValueError("malformed ExecStart") from exc
    if len(arguments) < 5 or arguments[0] != "/usr/bin/python3":
        raise ValueError("unrecognized console supervisor command")
    candidate = Path(arguments[1])
    if "--socket" not in arguments or "--" not in arguments:
        raise ValueError("incomplete pinned supervisor command")
    match = _VERSION.fullmatch(candidate.name)
    if not match or candidate.parent != directory:
        raise ValueError("unit references a replaceable or unknown supervisor")
    if arguments.count(str(candidate)) != 1:
        raise ValueError("duplicate supervisor path")
    return str(candidate)


def retention_plan(
    versions_dir: Path, *, installed_units: Mapping[str, str] | None,
    running_units: list[Mapping[str, Any]] | None, expected_units: list[str] | None,
) -> dict[str, Any]:
    """Report protected version paths, without ever unlinking any file.

    Caller-provided running identity is diagnostic. A production gate must
    independently confirm systemd/cgroup ownership and reconcile all hosts.
    """
    blockers: list[str] = []
    paths: list[str] = []
    active_refs: list[str] = []
    installed_refs: list[str] = []
    root = Path(versions_dir)
    if root.is_symlink() or not root.is_dir() or not root.is_absolute():
        blockers.append("unsafe_version_directory")
    else:
        try:
            info = root.stat()
            if info.st_mode & 0o022:
                blockers.append("writable_version_directory")
            for file in sorted(root.iterdir()):
                if not _VERSION.fullmatch(file.name):
                    blockers.append("unexpected_version_directory_entry")
                    continue
                if file.is_symlink() or not file.is_file():
                    blockers.append("unsafe_versioned_supervisor_file")
                    continue
                st = file.stat()
                if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                        or st.st_mode & 0o222 or st.st_size == 0
                        or st.st_size > 1024 * 1024):
                    blockers.append("unsafe_versioned_supervisor_file")
                    continue
                data = file.read_bytes()
                if hashlib.sha256(data).hexdigest() != _VERSION.fullmatch(file.name).group(1):
                    blockers.append("corrupt_versioned_supervisor_file")
                    continue
                paths.append(str(file))
        except OSError:
            blockers.append("version_inventory_failed")
    expected: list[str] = []
    if (not isinstance(expected_units, list) or not expected_units
            or len(set(x for x in expected_units if isinstance(x, str))) != len(expected_units)
            or any(not isinstance(x, str) or not _UNIT.fullmatch(x)
                   for x in expected_units)):
        blockers.append("expected_unit_inventory_invalid")
    else:
        expected = sorted(expected_units)

    if not isinstance(installed_units, Mapping) or set(installed_units) != set(expected):
        blockers.append("installed_unit_inventory_incomplete")
    else:
        for name in expected:
            try:
                installed_refs.append(_pin_from_unit(installed_units[name], root))
            except (ValueError, TypeError):
                blockers.append(name + ":installed_supervisor_not_pinned")

    observed: dict[str, Mapping[str, Any]] = {}
    if not isinstance(running_units, list):
        blockers.append("running_unit_inventory_missing")
    else:
        for row in running_units:
            if not isinstance(row, Mapping) or not isinstance(row.get("unit"), str):
                blockers.append("malformed_running_unit_observation")
                continue
            unit = row["unit"]
            if unit in observed:
                blockers.append("duplicate_running_unit_observation")
            observed[unit] = row
        if set(observed) != set(expected):
            blockers.append("running_unit_inventory_incomplete")
        for name in expected:
            row = observed.get(name)
            if row is None:
                continue
            if (type(row.get("pid")) is not int or row["pid"] <= 1
                    or type(row.get("start_stamp")) is not int
                    or row["start_stamp"] <= 0
                    or row.get("state") != "active"):
                blockers.append(name + ":running_process_identity_invalid")
            path = row.get("supervisor_path")
            if not isinstance(path, str) or not path:
                blockers.append(name + ":running_supervisor_unverified")
            else:
                active_refs.append(path)
                try:
                    candidate = Path(path)
                    if (candidate.parent != root
                            or not _VERSION.fullmatch(candidate.name)):
                        blockers.append(name + ":running_supervisor_unpinned")
                except (ValueError, TypeError):
                    blockers.append(name + ":running_supervisor_unpinned")

    required = set(active_refs) | set(installed_refs)
    if not required.issubset(paths):
        blockers.append("referenced_version_missing_or_unverifiable")
    return {
        "kind": "Capivara928SupervisorRetention",
        "schema_version": 1,
        "scope": "read_only_incomplete_without_live_systemd_attestation",
        "protected_running_versions": sorted(set(active_refs)),
        "protected_installed_versions": sorted(set(installed_refs)),
        "retained_versions": sorted(paths),
        "manual_review_only_unreferenced_versions": (
            sorted(set(paths) - required) if not blockers else []
        ),
        "blockers": sorted(set(blockers)),
        "inventory_consistent": not blockers,
        "automatic_deletion_allowed": False,
        "live_no_drain_authorized": False,
    }
