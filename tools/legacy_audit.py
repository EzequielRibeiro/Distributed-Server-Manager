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
    "systemd/dsm-notification-center.timer",
    "systemd/dsm-notification-engine.timer",
    "systemd/dsm-discord-worker.service",
    "systemd/dsm-discord.service",
    "dashboard/workers/events_worker.sh",
    "dashboard/workers/event_queue_worker.sh",
    "dashboard/workers/alerts_worker.sh",
    "dashboard/workers/collect_alerts.sh",
    "dashboard/alerts/alert_engine.sh",
    "dashboard/api/alerts.sh",
    "dashboard/notifications/notification_engine.sh",
    "dashboard/notifications/notification_center.sh",
    "dashboard/notifications/discord_worker.sh",
    "dashboard/notifications/notification_queue.json",
    "dashboard/notifications/.discord_pending",
    "dashboard/notifications/discord.conf",
    "monitor/alert_engine.sh",
    "core/alert_db.sh",
    "core/alert_history.sh",
    "core/notification_center.sh",
    "core/discord_sender.sh",
    "core/discord_queue.sh",
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

DSM_PATH_PATTERN = re.compile(r"/opt/dsm/([A-Za-z0-9_./-]+)")
TIMER_UNIT_PATTERN = re.compile(r"^Unit=([^\s]+)$", re.M)


def tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line for line in proc.stdout.splitlines() if line]


def audit_systemd(systemd_dir: Path, failures: list[str]) -> None:
    if not systemd_dir.is_dir():
        return

    units = sorted(
        path
        for path in systemd_dir.iterdir()
        if path.is_file() and path.suffix in {".service", ".timer"}
    )
    unit_names = {path.name for path in units}

    for unit in units:
        text = unit.read_text(encoding="utf-8", errors="replace")
        relative_unit = unit.relative_to(ROOT)

        if unit.suffix == ".service" and re.search(
            r"^Description=.*\bLegacy\b", text, re.M | re.I
        ):
            failures.append(f"service still identifies itself as legacy: {relative_unit}")

        for match in DSM_PATH_PATTERN.finditer(text):
            relative = match.group(1).rstrip("/.,;:")
            if relative and not (ROOT / relative).exists():
                failures.append(
                    f"systemd unit references missing project path: {relative_unit} -> {relative}"
                )

        if unit.suffix == ".timer":
            target_match = TIMER_UNIT_PATTERN.search(text)
            if target_match:
                target = target_match.group(1).strip()
                if target not in unit_names:
                    failures.append(
                        f"timer references missing unit: {relative_unit} -> {target}"
                    )


def main() -> int:
    files = tracked_files()
    file_set = set(files)
    failures: list[str] = []

    for path in sorted(RETIRED_PATHS & file_set):
        failures.append(f"retired artifact is still tracked: {path}")

    for path in files:
        if any(pattern.search(path) for pattern in JUNK_PATTERNS):
            failures.append(f"backup/copy artifact is tracked: {path}")

    audit_systemd(ROOT / "systemd", failures)

    aggregate = ROOT / "dashboard" / "workers" / "worker.sh"
    if aggregate.is_file():
        aggregate_text = aggregate.read_text(encoding="utf-8")
        for retired_worker in ("events_worker.sh", "event_queue_worker.sh", "alerts_worker.sh"):
            if retired_worker in aggregate_text:
                failures.append(f"aggregate dashboard worker still launches retired {retired_worker}")

    state_initializer = ROOT / "dashboard" / "state" / "init_state.sh"
    if state_initializer.is_file():
        state_text = state_initializer.read_text(encoding="utf-8")
        match = re.search(r"FILES=\((.*?)\)", state_text, re.S)
        initializer_entries = set(match.group(1).split()) if match else set()
        for durable_projection in ("alerts", "events"):
            if durable_projection in initializer_entries:
                failures.append(
                    f"dashboard state initializer recreates durable projection: {durable_projection}_state.json"
                )

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
