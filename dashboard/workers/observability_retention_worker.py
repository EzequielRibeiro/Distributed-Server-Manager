#!/usr/bin/env python3
"""Bound historical observability storage without affecting latest-value telemetry."""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[2])).resolve()
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from observability_repository import ObservabilityRepository
from runtime_backend import backend_from_environment

INTERVAL_SECONDS = max(60, min(int(os.environ.get("DSM_OBSERVABILITY_RETENTION_WORKER_SECONDS", "300")), 3600))
RETENTION_DAYS = max(1, min(int(os.environ.get("DSM_OBSERVABILITY_RETENTION_DAYS", "7")), 365))
BATCH_SIZE = max(100, min(int(os.environ.get("DSM_OBSERVABILITY_RETENTION_BATCH_SIZE", "5000")), 50000))
_ALLOWED_DB_KEYS = {
    "DSM_DATABASE_DRIVER",
    "DSM_DATABASE",
    "DSM_DATABASE_HOST",
    "DSM_DATABASE_PORT",
    "DSM_DATABASE_NAME",
    "DSM_DATABASE_USER",
    "DSM_DATABASE_PASSWORD_FILE",
    "DSM_DATABASE_TLS",
}


def _read_shell_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    pattern = re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            result[match.group(1)] = next(
                (value for value in match.groups()[1:] if value is not None),
                "",
            )
    return result


def _database_environment(root: Path = ROOT, environment: dict[str, str] | None = None) -> dict[str, str]:
    effective = dict(os.environ if environment is None else environment)
    for key, value in _read_shell_values(root / "config" / "dsm.conf").items():
        if key in _ALLOWED_DB_KEYS and key not in effective:
            effective[key] = value
    effective.setdefault("DSM_ROOT", str(root))
    return effective


class ObservabilityRetentionWorker:
    def __init__(
        self,
        backend,
        *,
        retention_days: int = RETENTION_DAYS,
        batch_size: int = BATCH_SIZE,
    ):
        self.repo = ObservabilityRepository(backend)
        self.repo.initialize()
        self.retention_days = max(1, min(int(retention_days), 365))
        self.batch_size = max(100, min(int(batch_size), 50000))

    def tick(self, now: datetime | None = None) -> dict[str, int | str]:
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff = (instant - timedelta(days=self.retention_days)).isoformat().replace("+00:00", "Z")
        pending = self.repo.count_before(cutoff)
        deleted = self.repo.prune_before(cutoff, limit=self.batch_size) if pending else 0
        return {
            "retention_days": self.retention_days,
            "cutoff": cutoff,
            "pending": pending,
            "deleted": deleted,
        }


def run_forever(root: Path = ROOT, interval: int = INTERVAL_SECONDS) -> None:
    backend = backend_from_environment(_database_environment(root))
    worker = ObservabilityRetentionWorker(backend)
    while True:
        try:
            report = worker.tick()
            if report["deleted"] or report["pending"]:
                print(
                    f"observability retention cutoff={report['cutoff']} "
                    f"pending={report['pending']} deleted={report['deleted']}",
                    flush=True,
                )
        except Exception as exc:
            print(f"observability retention worker failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(max(60, int(interval)))


if __name__ == "__main__":
    run_forever()
