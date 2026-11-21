#!/usr/bin/env python3
"""Read-only local Worker process identity / in-flight evidence for DSM #928.

The systemd MainPID, its nine immediate children and kernel start stamps
are checked twice. This is diagnostic ONLY: no no-drain ACK or update
authorization, even when every local Worker is present and its lock is free.
It never writes a marker, a PID file, a journal, or a systemd unit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
from typing import Any

from maintenance_hold_gate import _KNOWN_WORKERS, inspect_operation

UNIT = "dsm-dashboard-worker.service"
ROOT = Path("/opt/dsm")
UNIT_KEYS = ("ActiveState", "SubState", "MainPID", "User", "ControlGroup")
PID_RE = re.compile(r"[1-9][0-9]*\Z")


def _unit_status() -> dict[str, str]:
    result = subprocess.run(
        ("systemctl", "show", UNIT, "--no-pager",
         "--property=" + ",".join(UNIT_KEYS)),
        capture_output=True, text=True, check=False, timeout=6,
    )
    if result.returncode != 0:
        raise RuntimeError("systemd_unit_unavailable")
    props: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            raise RuntimeError("invalid_systemd_properties")
        key, value = line.split("=", 1)
        if key in props or key not in UNIT_KEYS:
            raise RuntimeError("ambiguous_systemd_properties")
        props[key] = value
    if set(props) != set(UNIT_KEYS):
        raise RuntimeError("incomplete_systemd_properties")
    return props


def _proc(pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    """Read Linux /proc identity, including the immutable kernel start tick."""
    if pid <= 0:
        raise ValueError("invalid PID")
    home = proc_root / str(pid)
    raw = (home / "stat").read_text()
    close = raw.rfind(")")
    if close < 0 or not raw.startswith(str(pid) + " ("):
        raise ValueError("invalid_proc_stat")
    fields = raw[close + 2:].split()
    if len(fields) < 20:
        raise ValueError("incomplete_proc_stat")
    state, ppid, ticks = fields[0], int(fields[1]), int(fields[19])
    if not state or state in ("Z", "X", "x") or ticks <= 0:
        raise ValueError("nonrunning_proc")
    uid_rows = [
        line.split() for line in (home / "status").read_text().splitlines()
        if line.startswith("Uid:")
    ]
    if len(uid_rows) != 1 or len(uid_rows[0]) < 3:
        raise ValueError("invalid_proc_uid")
    uid = int(uid_rows[0][2])  # effective UID
    cmd = (home / "cmdline").read_bytes()
    if not cmd or len(cmd) > 65536 or not cmd.endswith(b"\0"):
        raise ValueError("invalid_proc_command")
    argv = tuple(v.decode("utf-8", errors="replace")
                 for v in cmd[:-1].split(b"\0"))
    if len(argv) < 2:
        raise ValueError("incomplete_proc_command")
    cgroups = [
        line.split(":", 2)[2] for line in (home / "cgroup").read_text().splitlines()
        if line.startswith("0::") or ":name=systemd:" in line
    ]
    if len(cgroups) != 1:
        raise ValueError("unknown_process_cgroup")
    return {"pid": pid, "ppid": ppid, "start_ticks": ticks,
            "uid": uid, "state": state, "argv": argv, "cgroup": cgroups[0]}


def _snapshot(main_pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    supervisor = _proc(main_pid, proc_root)
    children_file = proc_root / str(main_pid) / "task" / str(main_pid) / "children"
    ids = children_file.read_text().split()
    if len(ids) != len(set(ids)) or any(not PID_RE.fullmatch(i) for i in ids):
        raise ValueError("invalid_children_inventory")
    children = [_proc(int(pid), proc_root) for pid in ids]
    return {"supervisor": supervisor, "children": children}


def evaluate(
    unit: dict[str, str], snapshot: dict[str, Any], locks: dict[str, str],
    *, expected_uid: int, root: Path = ROOT, stable: bool = True,
) -> dict[str, Any]:
    """Pure, fail-closed contract used by isolated fixtures and runtime."""
    expected = {name: ("scheduler_worker.sh" if name == "scheduler_worker"
                       else name + ".py") for name in _KNOWN_WORKERS}
    result: dict[str, Any] = {
        "status": "unverified",
        "supervisor_verified": False,
        "workers_verified": False,
        "locks_free_candidate": False,
        "live_no_drain_authorized": False,
        "workers": {},
        "errors": [],
    }
    errors: list[str] = result["errors"]
    group = unit.get("ControlGroup", "")
    pid_text = unit.get("MainPID", "")
    if (unit.get("ActiveState") != "active"
            or unit.get("SubState") != "running"
            or not PID_RE.fullmatch(pid_text)
            or not group.endswith("/" + UNIT)
            or not group.startswith("/")):
        errors.append("systemd_unit_not_verified")
        return result
    parent = snapshot.get("supervisor") or {}
    pid = int(pid_text)
    parent_argv = (parent.get("argv") or ())
    supervisor_file = str(root / "dashboard/workers/worker.sh")
    if (parent.get("pid") != pid or parent.get("start_ticks", 0) <= 0
            or parent.get("uid") != expected_uid
            or parent.get("cgroup") != group
            or len(parent_argv) < 2
            or Path(parent_argv[0]).name != "bash"
            or parent_argv[1] != supervisor_file):
        errors.append("supervisor_identity_mismatch")
        return result
    result["supervisor_verified"] = True
    result["supervisor"] = {
        "pid": pid, "start_ticks": parent["start_ticks"], "uid": expected_uid,
    }
    seen = set()
    children = snapshot.get("children") or []
    if len(children) != len(expected):
        errors.append("worker_count_mismatch")
    for proc in children:
        cmd = proc.get("argv") or ()
        script = cmd[1] if len(cmd) >= 2 else ""
        name = Path(script).stem
        if name not in expected or script != str(root / "dashboard/workers" / expected.get(name, "")):
            errors.append("unexpected_worker_child")
            continue
        if name in seen:
            errors.append("duplicate_worker_child")
            continue
        seen.add(name)
        program = Path(cmd[0]).name
        interpreter_valid = (
            program == "bash" if name == "scheduler_worker"
            else bool(re.fullmatch(r"python3(?:\.[0-9]+)?", program))
        )
        if (not interpreter_valid or proc.get("ppid") != pid
                or proc.get("uid") != expected_uid
                or proc.get("cgroup") != group
                or proc.get("start_ticks", 0) <= 0):
            errors.append("worker_identity_mismatch:" + name)
            continue
        result["workers"][name] = {
            "pid": proc["pid"],
            "start_ticks": proc["start_ticks"],
            "lock_status": locks.get(name, "unverified"),
        }
    if set(result["workers"]) != set(expected):
        errors.append("worker_inventory_incomplete")
    if not stable:
        errors.append("identity_changed_during_observation")
    result["workers_verified"] = not errors
    result["locks_free_candidate"] = (
        result["workers_verified"]
        and all(locks.get(n) == "lock_free_process_identity_unverified"
                for n in expected)
    )
    # Even with all nine Workers identified, locks cannot prove that a
    # dispatched job, subprocess, HTTP handler or remote Agent has finished.
    result["status"] = ("local_identity_verified_only"
                        if result["workers_verified"] else "unverified")
    return result


def inspect(*, proc_root: Path = Path("/proc"),
            root: Path = ROOT) -> dict[str, Any]:
    """Observe two snapshots and all nine locks; always fail closed."""
    failure = {"status": "unverified", "live_no_drain_authorized": False,
               "errors": ["observation_unavailable"]}
    try:
        before = _unit_status()
        if not PID_RE.fullmatch(before.get("MainPID", "")):
            raise ValueError("invalid_supervisor_pid")
        one = _snapshot(int(before["MainPID"]), proc_root)
        two = _snapshot(int(before["MainPID"]), proc_root)
        after = _unit_status()
        same_unit = before == after
        def identity(snap: dict[str, Any]) -> tuple:
            procs = [snap["supervisor"], *snap["children"]]
            return tuple(sorted(
                (p["pid"], p["ppid"], p["start_ticks"], p["uid"],
                 p["argv"], p["cgroup"]) for p in procs
            ))
        stable = same_unit and identity(one) == identity(two)
        locks = {
            name: str(inspect_operation(name, root=root)["status"])
            for name in sorted(_KNOWN_WORKERS)
        }
        if not before.get("User"):
            raise ValueError("missing_systemd_user")
        expected_uid = pwd.getpwnam(before["User"]).pw_uid
        return evaluate(after, two, locks, root=root,
                        expected_uid=expected_uid, stable=stable)
    except (OSError, ValueError, RuntimeError, KeyError,
            subprocess.SubprocessError) as exc:
        # Error category only, never print tokens, commands or environment.
        return {**failure, "errors": [type(exc).__name__]}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--inspect"]:
        return 2
    print(json.dumps(inspect(), sort_keys=True))
    # Never return 0: a successful diagnostic is NOT a no-drain permission.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
