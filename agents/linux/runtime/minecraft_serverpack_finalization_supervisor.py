"""Nonblocking and bounded launcher for supervised finalization workers.

The heartbeat process never performs an archive, restore or readiness wait.
Each worker acquires the existing cross-process per-instance runtime lock.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


class FinalizationWorkerSupervisor:
    def __init__(self, *, minimum_retry_seconds: float = 120,
                 clock: Callable[[], float] = time.monotonic,
                 spawn: Callable[..., Any] = subprocess.Popen):
        self._clock = clock
        self._spawn = spawn
        self._minimum_retry = max(60, float(minimum_retry_seconds))
        self._processes: dict[str, Any] = {}
        self._last_attempt: dict[str, float] = {}

    def launch(self, *, instance_id: str, config_path: Path, state_dir: Path) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        if (not instance_id or len(instance_id) > 191
                or any(c not in allowed for c in instance_id)):
            raise ValueError("unsafe worker instance identity")
        if not Path(config_path).is_absolute() or not Path(state_dir).is_absolute():
            raise ValueError("worker paths must be absolute")
        previous = self._processes.get(instance_id)
        if previous is not None and previous.poll() is None:
            return "already_running"
        now = self._clock()
        last = self._last_attempt.get(instance_id)
        if last is not None and now - last < self._minimum_retry:
            return "cooldown"
        worker = Path(__file__).with_name("minecraft_serverpack_finalization_worker.py")
        if not worker.is_file():
            raise RuntimeError("finalization worker is missing")
        log_dir = Path(state_dir) / "finalization-worker"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{instance_id}.log"
        if log_file.is_symlink():
            raise RuntimeError("unsafe finalization log")
        if log_file.exists() and log_file.stat().st_size > 262144:
            log_file.replace(log_file.with_suffix(".old.log"))
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(log_file, flags, 0o600)
        self._last_attempt[instance_id] = now
        try:
            with os.fdopen(fd, "ab", buffering=0) as log:
                child = self._spawn(
                    [sys.executable, str(worker), str(config_path), instance_id],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    close_fds=True, start_new_session=True,
                )
        except Exception:
            # Retry after cooldown, never tight-loop a broken worker.
            raise
        self._processes[instance_id] = child
        return "started"
