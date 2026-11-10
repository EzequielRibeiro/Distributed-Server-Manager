"""Read-only, Linux-only live JVM boot witness for Server Pack observations.

An existing log line is not boot proof unless it belongs to the current owned
systemd process tree. This is advisory evidence, never health/release authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import subprocess
from typing import Any

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_DONE = re.compile(
    r"^\[(\d{2}[A-Z][a-z]{2}\d{4} \d{2}:\d{2}:\d{2}\.\d{3})\]"
    r" \[Server thread/INFO\] \[net\.minecraft\.server\.dedicated\.DedicatedServer/\]:"
    r" Done \([\d.]+s\)!"
)


def _process_start(pid: int) -> datetime:
    # /proc/PID/stat field 22. Split after the final ')' to handle spaces in comm.
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    rest = stat.rsplit(")", 1)[1].split()
    ticks = int(rest[19])
    boot_line = next(
        line for line in Path("/proc/stat").read_text(encoding="ascii").splitlines()
        if line.startswith("btime ")
    )
    epoch = int(boot_line.split()[1]) + ticks / os.sysconf("SC_CLK_TCK")
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _command(pid: int) -> list[str]:
    raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    return [x.decode("utf-8", errors="replace") for x in raw.split(b"\0") if x]


def observe_boot_witness(
    runtime: Path, *, instance_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect the current owned service, JVM child and fresh Done log.

    Fail closed on stale logs, wrong process, wrong working directory or a
    process change. Does not assert that the modpack is functionally healthy.
    """
    negative = {"status": "boot_unverified", "boot_verified": False,
                "ready_for_release": False}
    if not isinstance(instance_id, str) or not _TOKEN.fullmatch(instance_id):
        return {**negative, "reason": "invalid_instance"}
    runtime = Path(runtime)
    if not runtime.is_absolute() or runtime.is_symlink() or not runtime.is_dir():
        return {**negative, "reason": "unsafe_runtime"}
    unit = f"capivara-instance-{instance_id}.service"
    try:
        reply = subprocess.run(
            ["systemctl", "show", unit, "-p", "MainPID", "-p", "ActiveState",
             "-p", "WorkingDirectory"],
            capture_output=True, text=True, timeout=4, check=True,
        )
        props = dict(line.split("=", 1) for line in reply.stdout.splitlines()
                     if "=" in line)
        supervisor = int(props.get("MainPID", "0"))
        if (props.get("ActiveState") != "active" or supervisor <= 1
                or Path(props.get("WorkingDirectory", "")).resolve() != runtime.resolve()):
            return {**negative, "reason": "service_not_bound"}
        supervisor_cmd = _command(supervisor)
        if (not any(arg.endswith("/console_supervisor.py") for arg in supervisor_cmd)
                or not any(instance_id in arg for arg in supervisor_cmd)):
            return {**negative, "reason": "supervisor_not_bound"}
        children = Path(f"/proc/{supervisor}/task/{supervisor}/children").read_text().split()
        candidates = []
        for child in children:
            pid = int(child)
            args = _command(pid)
            if (args and Path(args[0]).name == "java"
                    and "@capivara-launch.args" in args
                    and Path(f"/proc/{pid}/cwd").resolve() == runtime.resolve()):
                candidates.append(pid)
        if len(candidates) != 1:
            return {**negative, "reason": "java_process_not_unique"}
        java_pid = candidates[0]
        java_started = _process_start(java_pid)
        clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if java_started > clock + timedelta(seconds=2):
            return {**negative, "reason": "future_java_start"}
        log = runtime / "logs/latest.log"
        if log.is_symlink() or not log.is_file() or log.stat().st_size > 16 * 1024 * 1024:
            return {**negative, "reason": "unsafe_log"}
        # Logs are in system-local time (not UTC); compare both times in UTC.
        local_tz = datetime.now().astimezone().tzinfo
        done_at = None
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _DONE.match(line)
            if not match:
                continue
            when = datetime.strptime(match.group(1), "%d%b%Y %H:%M:%S.%f")
            when = when.replace(tzinfo=local_tz).astimezone(timezone.utc)
            if java_started - timedelta(seconds=3) <= when <= clock + timedelta(seconds=2):
                done_at = when
        if done_at is None:
            return {**negative, "reason": "no_current_java_done"}
        if done_at - java_started > timedelta(minutes=30):
            return {**negative, "reason": "boot_window_exceeded"}
        # Guard races with exit/restart and PID reuse while reading the log.
        if _process_start(java_pid) != java_started or not Path(f"/proc/{java_pid}").exists():
            return {**negative, "reason": "java_process_changed"}
        return {
            **negative, "status": "boot_process_observed",
            "reason": "current_java_and_done_log_bound",
            "java_pid": java_pid,
            "java_started_at": java_started.isoformat(),
            "done_at": done_at.isoformat(),
            "proof_scope": "advisory_current_process_log",
        }
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return {**negative, "reason": "boot_probe_unavailable"}


__all__ = ["observe_boot_witness"]
