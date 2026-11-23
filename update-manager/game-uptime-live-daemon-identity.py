#!/usr/bin/env python3
"""#928: read-only daemon identity + Controller flock opt-in observation.

Verifies ACTUAL systemd PID, kernel start time, cgroup, executable script,
effective UID and the Controller's startup flock opt-in. Reuses the existing
nine-child Worker identity verifier; never infers an ACK from this snapshot.

No writes, no lock acquisition, no credential values in the result.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys

CONTROLLER_UNIT = "dsm-dashboard.service"
CONTROLLER_SCRIPT = Path("/opt/dsm/dashboard/server_part22.py")
WORKER_ROOT = Path("/opt/dsm")
_EXPECTED_PROPERTIES = ("ActiveState", "SubState", "MainPID", "User", "ControlGroup")
_PID_RE = re.compile(r"[1-9][0-9]*\Z")


def _systemd_status(unit: str) -> dict[str, str]:
    result = subprocess.run(
        ("systemctl", "show", unit, "--no-pager",
         "--property=" + ",".join(_EXPECTED_PROPERTIES)),
        capture_output=True, text=True, check=False, timeout=7)
    if result.returncode != 0:
        raise ValueError("systemd_controller_unavailable")
    items = {}
    for line in result.stdout.splitlines():
        if line.count("=") < 1:
            raise ValueError("malformed_systemd_properties")
        name, value = line.split("=", 1)
        if name not in _EXPECTED_PROPERTIES or name in items:
            raise ValueError("untrusted_systemd_properties")
        items[name] = value
    if set(items) != set(_EXPECTED_PROPERTIES):
        raise ValueError("incomplete_systemd_properties")
    return items


def _controller_pid(pid: int, *, proc_root: Path = Path("/proc")) -> dict:
    base = proc_root / str(pid)
    raw = (base / "stat").read_text()
    close = raw.rfind(")")
    if close < 0 or not raw.startswith(str(pid) + " ("):
        raise ValueError("malformed_controller_stat")
    fields = raw[close + 2:].split()
    if len(fields) < 20 or fields[0] in ("Z", "X", "x"):
        raise ValueError("controller_not_running")
    ticks = int(fields[19])
    if ticks < 1:
        raise ValueError("invalid_controller_start_ticks")
    uid_lines = [x.split() for x in (base / "status").read_text().splitlines()
                 if x.startswith("Uid:")]
    if len(uid_lines) != 1 or len(uid_lines[0]) < 3:
        raise ValueError("unreadable_controller_uid")
    uid = int(uid_lines[0][2])
    cmd = (base / "cmdline").read_bytes()
    if not cmd or len(cmd) > 16384 or not cmd.endswith(b"\x00"):
        raise ValueError("malformed_controller_argv")
    args = tuple(x.decode("utf-8", "replace") for x in cmd[:-1].split(b"\x00"))
    groups = [x.split(":", 2)[2] for x in
              (base / "cgroup").read_text().splitlines()
              if x.startswith("0::") or ":name=systemd:" in x]
    if len(groups) != 1:
        raise ValueError("controller_cgroup_unknown")
    data = (base / "environ").read_bytes()
    if len(data) > 262144 or not data.endswith(b"\x00"):
        raise ValueError("controller_environment_unavailable")
    entries = data[:-1].split(b"\x00")
    optin = [x.split(b"=", 1)[1] for x in entries
             if x.startswith(b"DSM928_CONTROLLER_AGENT_HTTP_FLOCK=")]
    # Only a boolean is returned. Do not print or serialize the environment.
    return {
        "pid": pid, "uid": uid, "start_ticks": ticks, "argv": args,
        "cgroup": groups[0],
        "flock_opted_in": len(optin) == 1 and optin[0] == b"1",
    }


def verify_controller_snapshot(before: dict, after: dict,
                               first: dict, second: dict, *,
                               expected_uid: int,
                               script: Path = CONTROLLER_SCRIPT) -> bool:
    """Validate stable systemd and kernel identities; return only opt-in."""
    if (before != after
            or before.get("ActiveState") != "active"
            or before.get("SubState") != "running"
            or not _PID_RE.fullmatch(before.get("MainPID", ""))
            or before.get("ControlGroup") != "/system.slice/" + CONTROLLER_UNIT
            or first != second):
        raise ValueError("controller_process_identity_unstable")
    pid = int(before["MainPID"])
    args = first.get("argv") or ()
    if (first.get("pid") != pid
            or type(first.get("start_ticks")) is not int
            or first["start_ticks"] < 1
            or first.get("uid") != expected_uid
            or first.get("cgroup") != before["ControlGroup"]
            or len(args) < 2
            or not re.fullmatch(r"python3(?:\.[0-9]+)?", Path(args[0]).name)
            or args[1] != str(script)):
        raise ValueError("controller_process_identity_mismatch")
    return first.get("flock_opted_in") is True


def _controller_identity(*, unit: str = CONTROLLER_UNIT,
                         script: Path = CONTROLLER_SCRIPT) -> dict:
    summary = {
        "status": "unverified", "identity_verified": False,
        "flock_opted_in_verified": False, "live_no_drain_authorized": False,
    }
    try:
        # This runtime diagnostic must not be redirected to another unit
        # or source tree to fabricate a production readiness signal.
        if unit != CONTROLLER_UNIT or Path(script) != CONTROLLER_SCRIPT:
            raise ValueError("production_unit_or_script_override")
        before = _systemd_status(unit)
        if (before["ActiveState"] != "active"
                or before["SubState"] != "running"
                or not _PID_RE.fullmatch(before["MainPID"])
                or not before["User"]
                or before["ControlGroup"] != "/system.slice/" + unit):
            raise ValueError("controller_unit_identity_unverified")
        expected_uid = pwd.getpwnam(before["User"]).pw_uid
        pid = int(before["MainPID"])
        one = _controller_pid(pid)
        two = _controller_pid(pid)
        after = _systemd_status(unit)
        opted_in = verify_controller_snapshot(
            before, after, one, two, expected_uid=expected_uid, script=script)
        source = script.lstat()
        if not stat.S_ISREG(source.st_mode):
            raise ValueError("controller_source_not_regular")
        summary.update(
            status="controller_identity_verified_only",
            identity_verified=True,
            flock_opted_in_verified=opted_in,
            pid=pid, start_ticks=one["start_ticks"],
        )
    except (OSError, ValueError, KeyError, LookupError,
            subprocess.SubprocessError) as exc:
        summary["reason"] = type(exc).__name__
    return summary


def _workers_identity() -> dict:
    result = {
        "status": "unverified", "supervisor_verified": False,
        "all_nine_workers_verified": False, "live_no_drain_authorized": False,
    }
    try:
        directory = Path(__file__).resolve().parents[1] / "dashboard/workers"
        if str(directory) not in sys.path:
            sys.path.append(str(directory))
        from worker_identity_diagnostic import inspect
        witness = inspect(root=WORKER_ROOT)
        workers = witness.get("workers") or {}
        verified = (witness.get("status") == "local_identity_verified_only"
                    and witness.get("supervisor_verified") is True
                    and witness.get("workers_verified") is True
                    and len(workers) == 9
                    and set(workers) == {
                        "scheduler_worker", "automation_worker",
                        "content_update_worker", "maintenance_worker",
                        "observability_retention_worker",
                        "content_upload_retention_worker",
                        "database_intelligence_worker", "hybrid_agent_worker",
                        "hybrid_customer_workspace_worker",
                    })
        result.update(
            status="worker_process_identities_verified_only"
                   if verified else "unverified",
            supervisor_verified=bool(witness.get("supervisor_verified")),
            all_nine_workers_verified=bool(verified),
            observed_worker_count=len(workers),
        )
    except (OSError, ValueError, KeyError, RuntimeError,
            subprocess.SubprocessError) as exc:
        result["reason"] = type(exc).__name__
    return result


def observe() -> dict:
    """Snapshot real installed daemons; no persistent fence and NO ACK."""
    controller = _controller_identity()
    workers = _workers_identity()
    blockers = []
    if not controller["identity_verified"]:
        blockers.append("controller_live_process_identity_unverified")
    if not controller["flock_opted_in_verified"]:
        blockers.append("controller_flock_startup_opt_in_unverified")
    if not workers["all_nine_workers_verified"]:
        blockers.append("worker_supervisor_or_child_process_identity_unverified")
    blockers.extend([
        "daemon_lock_coverage_and_inflight_jobs_not_proven",
        "remote_agent_quiescence_not_acknowledged",
        "transactional_fence_not_held_by_live_updater",
    ])
    return {
        "kind": "DSM928InstalledDaemonIdentityObservation",
        "status": "read_only_partial_daemon_identity",
        "controller": controller,
        "worker_group": workers,
        "blockers": blockers,
        "controller_mutations_acked": False,
        "worker_cycles_acked": False,
        "remote_agents_acked": False,
        "external_jobs_acked": False,
        "live_no_drain_authorized": False,
    }
