#!/usr/bin/env python3
"""Read-only systemd game-process preservation gate; no update authorization.

An unsafe or unverifiable unit must block any attempted no-drain transaction.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

UNIT = re.compile(r"^capivara-instance-[A-Za-z0-9_.-]+\.service$")
CONTROL_PREFIXES = ("dsm-", "capivara-agent-", "capivara-hybrid-")
CONTROL_EXACT = frozenset(("capivara-agent.service", "capivara-hybrid-agent.service"))
# Evaluate both forward and reverse relations. A control-plane restart can
# indirectly affect game units through Conflicts or reverse systemd links even
# when the game's direct PartOf/BindsTo list looks safe. Unavailable properties
# intentionally fail closed in the read-only no-drain diagnosis.
DEPENDENCY_PROPERTIES = ("PartOf", "BindsTo", "Requires", "Requisite",
                         "Wants", "Upholds", "Conflicts", "Triggers",
                         "StopPropagatedFrom", "PropagatesStopTo",
                         "BoundBy", "ConsistsOf", "RequiredBy", "WantedBy",
                         "UpheldBy", "ConflictedBy", "TriggeredBy")
# Paths in lifecycle hooks and working-directory/environment directives can
# reference replaceable DSM code even when the main game ExecStart is stable.
LIFECYCLE_PROPERTIES = ("ExecCondition", "ExecStartPre", "ExecStartPost",
                        "ExecStop", "ExecStopPost", "ExecReload")
PATH_PROPERTIES = ("WorkingDirectory", "EnvironmentFiles", "RootDirectory", "RootImage")
RUNTIME_REFERENCES = ("/opt/dsm/agents/", "/opt/dsm/dashboard/",
                      "/opt/dsm/core/", "/opt/dsm/update-manager/",
                      "/opt/dsm/bin/", "/opt/dsm/systemd/")


class GateError(RuntimeError):
    pass


def _call(*args: str) -> str:
    process = subprocess.run(args, text=True, capture_output=True, check=False, timeout=8)
    if process.returncode:
        raise GateError("systemctl inspection failed")
    return process.stdout


def inspect(unit: str, call: Callable[..., str] = _call) -> dict[str, object]:
    if not UNIT.fullmatch(unit):
        raise GateError("invalid managed game unit name")
    props = ("ActiveState", "MainPID", "ExecMainStartTimestampMonotonic",
             "ExecStart", "FragmentPath", *DEPENDENCY_PROPERTIES,
             *LIFECYCLE_PROPERTIES, *PATH_PROPERTIES)
    raw = call("systemctl", "show", unit, *(f"--property={p}" for p in props),
               "--no-pager")
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k in props:
            data[k] = v.strip()
    # systemctl omits empty execution arrays even when explicitly requested.
    # Confirm their typed D-Bus values before interpreting omissions as empty.
    optional_arrays = dict.fromkeys(LIFECYCLE_PROPERTIES, "a(sasbttttuii)")
    optional_arrays["EnvironmentFiles"] = "a(sb)"
    missing_arrays = set(props) - data.keys()
    if missing_arrays - optional_arrays.keys():
        raise GateError("incomplete systemd evidence")
    if missing_arrays:
        escaped = "".join(char if char.isascii() and char.isalnum()
                          else f"_{ord(char):02x}" for char in unit)
        for name in sorted(missing_arrays):
            try:
                empty = json.loads(call(
                    "/usr/bin/busctl", "--json=short", "get-property", "org.freedesktop.systemd1",
                    "/org/freedesktop/systemd1/unit/" + escaped,
                    "org.freedesktop.systemd1.Service", name))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                raise GateError("incomplete systemd execution evidence") from exc
            if empty == {"type": optional_arrays[name], "data": []}:
                data[name] = ""
    if set(props) - data.keys():
        raise GateError("incomplete systemd evidence")
    if data["ActiveState"] != "active":
        raise GateError("instance is not active")
    pid = data["MainPID"]
    if not pid.isdecimal() or int(pid) <= 1:
        raise GateError("invalid game main PID")
    stamp = data["ExecMainStartTimestampMonotonic"]
    if not stamp.isdecimal() or int(stamp) <= 0:
        raise GateError("missing process start identity")
    exec_line = data["ExecStart"]
    if not exec_line or any(reference in exec_line for reference in RUNTIME_REFERENCES):
        raise GateError("game ExecStart points into replaceable DSM control-plane paths")
    for prop in (*LIFECYCLE_PROPERTIES, *PATH_PROPERTIES):
        if any(reference in data[prop] for reference in RUNTIME_REFERENCES):
            raise GateError(f"game {prop} points into replaceable DSM control-plane paths")
    for prop in DEPENDENCY_PROPERTIES:
        dependencies = data[prop].split()
        if any(dependency.startswith(CONTROL_PREFIXES) or dependency in CONTROL_EXACT
               for dependency in dependencies):
            raise GateError(f"game service has control-plane dependency: {prop}")
    fragment = data["FragmentPath"]
    if not fragment.startswith("/etc/systemd/system/") or ".." in Path(fragment).parts:
        raise GateError("untrusted game service unit location")
    # Capture the stable unit directives, not transient systemctl status fields.
    # Hash only: never expose EnvironmentFiles or lifecycle command strings
    # through public diagnostics, as they can contain deployment metadata.
    witness = {key: data[key] for key in
               ("ExecStart", "FragmentPath", *DEPENDENCY_PROPERTIES,
                *LIFECYCLE_PROPERTIES, *PATH_PROPERTIES)}
    unit_digest = hashlib.sha256(json.dumps(witness, sort_keys=True).encode()).hexdigest()
    return {"unit": unit, "main_pid": int(pid), "start_stamp": int(stamp),
            "exec": exec_line, "fragment": fragment,
            "unit_config_sha256": unit_digest}


def verify_unchanged(original: dict[str, object],
                     call: Callable[..., str] = _call) -> dict[str, object]:
    current = inspect(str(original["unit"]), call)
    if any(current.get(key) != original.get(key)
           for key in ("main_pid", "start_stamp", "exec", "fragment", "unit_config_sha256")):
        raise GateError("managed game process or systemd unit changed during transaction")
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit")
    args = parser.parse_args()
    try:
        result = inspect(args.unit)
    except (GateError, OSError, ValueError) as exc:
        print(json.dumps({"eligible": False, "reason": str(exc)}))
        return 2
    print(json.dumps({"eligible": False, "verified_snapshot": result,
                      "reason": "diagnostic only; no-drain transactions not authorized"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
