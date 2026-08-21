#!/usr/bin/env python3
"""Repository-wide legacy/dead-artifact audit for Capivara DSM.

The audit is intentionally conservative: it fails on artifacts that have been
formally retired and on accidental backup/copy files, while allowing documented
compatibility shims that are still required for upgrades or old installations.
"""
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
    "dashboard/workers/events_worker.sh",
}

# These are compatibility surfaces, not dead code. Removing them would break
# supported upgrades or current aggregate dashboard behaviour.
DOCUMENTED_COMPATIBILITY = {
    "update.sh",  # legacy runtime-account and worker-unit migration
    "dashboard/workers/dashboard_worker.sh",
    "dashboard/workers/server_worker.sh",
    "dashboard/workers/metrics_worker.sh",
    "dashboard/workers/monitor_worker.sh",
    "dashboard/workers/mods_worker.sh",
    "dashboard/workers/alerts_worker.sh",
    "dashboard/workers/backup_worker.sh",
    "dashboard/notifications/discord_worker.sh",
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
    if aggregate.is_file() and "events_worker.sh" in aggregate.read_text(encoding="utf-8"):
        failures.append("aggregate dashboard worker still launches retired events_worker.sh")

    if failures:
        print("Legacy audit: FAILED", file=sys.stderr)
        for item in failures:
            print(f" - {item}", file=sys.stderr)
        return 1

    print("Legacy audit: OK")
    print(f"Tracked files inspected: {len(files)}")
    print(f"Retired paths enforced: {len(RETIRED_PATHS)}")
    print(f"Documented compatibility surfaces: {len(DOCUMENTED_COMPATIBILITY)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
