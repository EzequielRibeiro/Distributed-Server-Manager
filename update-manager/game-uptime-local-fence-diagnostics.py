#!/usr/bin/env python3
"""#928: observe *actual* Controller/Worker in-flight kernel fences.

Read-only local diagnostics for the future operational no-drain handshake.
A free lock or valid hold is NOT an ACK or remote host quiescence. Neither
the Controller lock nor this worker inventory covers all DSM mutators yet.
No marker, lockfile, journal, or systemd unit is created or modified here.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat

CONTROLLER_LOCK = Path("/run/capivara-dsm/controller-agent-http.lock")
WORKER_LOCK_DIR = Path("/run/capivara-dsm/worker-operations")
WORKERS = (
    "automation_worker",
    "content_update_worker",
    "content_upload_retention_worker",
    "database_intelligence_worker",
    "hybrid_agent_worker",
    "hybrid_customer_workspace_worker",
    "maintenance_worker",
    "observability_retention_worker",
    "scheduler_worker",
)


def _inspect_lock(path: Path, *, kind: str,
                  expected_uid: int | None = None) -> dict:
    result = {"path": str(path), "status": "unverified",
              "in_flight": None, "live_no_drain_authorized": False}
    try:
        if path.is_symlink() or not path.is_absolute():
            raise ValueError("symlink_or_relative_lock")
        for folder in (path.parent.parent, path.parent):
            identity = folder.lstat()
            if (not stat.S_ISDIR(identity.st_mode)
                    or identity.st_uid != 0
                    or identity.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                raise ValueError("untrusted_lock_parent")
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or (expected_uid is not None and before.st_uid != expected_uid)):
            raise ValueError("untrusted_lock_inode")
        fd = os.open(
            path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0))
        try:
            now = os.fstat(fd)
            if (before.st_dev != now.st_dev or before.st_ino != now.st_ino
                    or not stat.S_ISREG(now.st_mode) or now.st_nlink != 1):
                raise ValueError("lock_identity_changed")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                result.update(status="in_flight_or_fenced", in_flight=True)
            else:
                result.update(status="lock_free_not_ack", in_flight=False)
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)[:90] or "unavailable"
    return result


def observe_local_fences(*, controller_lock: Path = CONTROLLER_LOCK,
                         worker_lock_dir: Path = WORKER_LOCK_DIR,
                         fixture_only: bool = False) -> dict:
    """Inspect installed lock inodes; custom paths only under disposable /tmp.

    This is a snapshot, not a retained lock. An actor can start new work
    immediately after inspection, therefore ALL affirmative ACK flags remain
    false even if no locks are currently held.
    """
    if fixture_only:
        import tempfile
        tmp = Path(tempfile.gettempdir()).resolve()
        candidate_controller = Path(controller_lock).resolve()
        candidate_workers = Path(worker_lock_dir).resolve()
        if (tmp not in candidate_controller.parents or
                tmp not in candidate_workers.parents):
            return {"status": "blocked_fixture_path", "controller_http_acked": False,
                    "workers_acked": False, "external_jobs_acked": False,
                    "remote_agents_acked": False, "live_no_drain_authorized": False}
    elif (Path(controller_lock) != CONTROLLER_LOCK
          or Path(worker_lock_dir) != WORKER_LOCK_DIR):
        return {"status": "untrusted_path_override",
                "controller_http_acked": False, "workers_acked": False,
                "external_jobs_acked": False, "remote_agents_acked": False,
                "live_no_drain_authorized": False}
    controller = _inspect_lock(Path(controller_lock), kind="controller_http")
    worker_statuses = {
        name: _inspect_lock(Path(worker_lock_dir) / (name + ".lock"), kind="worker")
        for name in WORKERS
    }
    return {
        "kind": "DSM928LocalKernelFenceSnapshot",
        "mode": "read_only",
        "status": "incomplete_live_admission_evidence",
        "controller_agent_http": controller,
        "workers": worker_statuses,
        "observed_worker_count": len(worker_statuses),
        "controller_http_acked": False,
        "workers_acked": False,
        "external_jobs_acked": False,
        "remote_agents_acked": False,
        "live_no_drain_authorized": False,
    }
