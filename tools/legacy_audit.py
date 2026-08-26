#!/usr/bin/env python3
"""Repository-wide retired-artifact audit for Capivara DSM."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED_PATHS = {
    "systemd/dsm-backup-worker.service",
    "systemd/dsm-events-worker.service",
    "systemd/dsm-metrics-worker.service",
    "systemd/dsm-mods-worker.service",
    "systemd/dsm-server-worker.service",
    "systemd/dsm-event-queue-worker.service",
    "systemd/dsm-notification-center.service",
    "systemd/dsm-notification-engine.service",
    "dashboard/workers/events_worker.sh",
    "dashboard/workers/event_queue_worker.sh",
    "dashboard/workers/alerts_worker.sh",
    "dashboard/workers/collect_alerts.sh",
    "dashboard/alerts/alert_engine.sh",
    "dashboard/api/alerts.sh",
    "dashboard/notifications/notification_engine.sh",
    "dashboard/notifications/notification_center.sh",
    "dashboard/notifications/discord_worker.sh",
    "monitor/alert_engine.sh",
    "core/alert_db.sh",
    "core/alert_history.sh",
    "database/alert_store.sh",
    "database/dashboard_activity_repository.py",
    "database/dashboard_activity_schema.py",
}

DOCUMENTED_COMPATIBILITY = {
    "update.sh",
    "dashboard/workers/dashboard_worker.sh",
    "dashboard/workers/server_worker.sh",
    "dashboard/workers/metrics_worker.sh",
    "dashboard/workers/monitor_worker.sh",
    "dashboard/workers/mods_worker.sh",
    "dashboard/workers/backup_worker.sh",
}

JUNK_PATTERNS = (
    re.compile(r"(?:^|/)(?:copy of |old_|old-|legacy_copy)", re.I),
    re.compile(r"\.(?:bak|backup|orig|rej|tmp|swp)$", re.I),
    re.compile(r"~$"),
)


def tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line for line in proc.stdout.splitlines() if line]


def main() -> int:
    files = tracked_files()
    file_set = set(files)
    failures: list[str] = []

    for path in sorted(RETIRED_PATHS & file_set):
        failures.append(f"retired artifact is still tracked: {path}")

    for path in files:
        if any(pattern.search(path) for pattern in JUNK_PATTERNS):
            failures.append(f"backup/copy artifact is tracked: {path}")

    systemd_dir = ROOT / "systemd"
    if systemd_dir.is_dir():
        for unit in sorted(systemd_dir.glob("*.service")):
            text = unit.read_text(encoding="utf-8", errors="replace")
            if re.search(r"^Description=.*\bLegacy\b", text, re.M | re.I):
                failures.append(f"service still identifies itself as legacy: {unit.relative_to(ROOT)}")

    aggregate = ROOT / "dashboard" / "workers" / "worker.sh"
    if aggregate.is_file():
        aggregate_text = aggregate.read_text(encoding="utf-8")
        for retired_worker in ("events_worker.sh", "event_queue_worker.sh", "alerts_worker.sh"):
            if retired_worker in aggregate_text:
                failures.append(f"aggregate dashboard worker still launches retired {retired_worker}")

    if failures:
        print("Legacy audit: FAILED", file=sys.stderr)
        for item in failures:
            print(f" - {item}", file=sys.stderr)
        return 1

    print("Legacy audit: OK")
    print(f"Tracked files inspected: {len(files)}")
    print(f"Retired paths enforced: {len(RETIRED_PATHS)}")
    print(f"Remaining separately-scoped compatibility surfaces: {len(DOCUMENTED_COMPATIBILITY)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
