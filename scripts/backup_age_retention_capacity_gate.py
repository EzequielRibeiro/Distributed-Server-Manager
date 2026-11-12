#!/usr/bin/env python3
"""Fail-closed, read-only 14-day backup retention capacity forecast.

Use before enabling the Controller age-retention opt-in. Never deletes backups,
mod caches, worlds or any other files. It does not change runtime scheduling.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

GIB = 1024 ** 3
INSTANCE_ID = re.compile(r"[A-Za-z0-9._-]{1,191}\Z")
ARCHIVE = re.compile(r"[0-9a-fA-F-]{36}\.tar(?:\.gz)?\Z")


def forecast(
    backup_root: Path,
    instance_ids: list[str],
    *,
    days: int = 14,
    copies_per_day: int = 1,
    reserve_gib: int = 20,
    safety_cycles: int = 1,
    now: datetime | None = None,
    available_bytes: int | None = None,
) -> dict:
    """Project *minimum* required free disk using current full-backup sizes.

    Assumes the current daily cadence continues. Adds one transient full
    backup per instance because Controller prunes only after the new ACK.
    A safety reserve is separate from this transient copy allowance.
    """
    if not instance_ids or len(set(instance_ids)) != len(instance_ids):
        raise ValueError("specify unique instance IDs")
    if any(value in {".", ".."} or not INSTANCE_ID.fullmatch(value) for value in instance_ids):
        raise ValueError("invalid instance ID")
    if not (1 <= days <= 365 and 1 <= copies_per_day <= 24
            and 1 <= reserve_gib <= 1000 and 1 <= safety_cycles <= 4):
        raise ValueError("invalid retention sizing parameters")
    root = Path(backup_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("backup root must be an existing non-symlink directory")
    root = root.resolve(strict=True)
    timestamp = (now or datetime.now(timezone.utc))
    if timestamp.tzinfo is None:
        raise ValueError("now must be timezone aware")
    threshold = timestamp.astimezone(timezone.utc) - timedelta(days=days)
    root_dev = root.stat().st_dev

    if available_bytes is None:
        stat = os.statvfs(root)
        available_bytes = int(stat.f_bavail) * int(stat.f_frsize)
    if type(available_bytes) is not int or available_bytes < 0:
        raise ValueError("invalid available disk size")

    projections = []
    required_growth = 0
    transient_slack = 0
    expected_total_copies = days * copies_per_day
    for instance_id in instance_ids:
        folder = root / instance_id
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError(f"missing or symlinked backup directory: {instance_id}")
        if folder.stat().st_dev != root_dev:
            raise ValueError(f"backup directory crosses filesystems: {instance_id}")
        archives = []
        for entry in folder.iterdir():
            if not ARCHIVE.fullmatch(entry.name):
                continue
            if entry.is_symlink() or not entry.is_file():
                raise ValueError(f"unsafe backup archive: {instance_id}/{entry.name}")
            st = entry.stat()
            if st.st_size <= 0:
                raise ValueError(f"empty backup archive: {instance_id}/{entry.name}")
            archives.append((st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc)))
        if not archives:
            raise ValueError(f"no baseline full backup available for: {instance_id}")
        # Using the largest observed full archive avoids underestimating
        # archive growth from historical compression differences.
        max_size = max(size for size, _ in archives)
        current = sum(1 for _, date in archives if date >= threshold)
        additional = max(0, expected_total_copies - current)
        growth = additional * max_size
        slack = max_size * safety_cycles
        required_growth += growth
        transient_slack += slack
        projections.append({
            "instance_id": instance_id,
            "existing_archives": len(archives),
            "within_retention_days": current,
            "expected_copies": expected_total_copies,
            "max_archive_bytes": max_size,
            "additional_archive_bytes": growth,
            "next_cycle_slack_bytes": slack,
        })

    reserve_bytes = reserve_gib * GIB
    required_bytes = required_growth + transient_slack + reserve_bytes
    shortage_bytes = max(0, required_bytes - available_bytes)
    return {
        "status": "pass" if shortage_bytes == 0 else "blocked_insufficient_capacity",
        "scope": "read_only_projection_no_restore_or_cleanup",
        "retention_days": days,
        "copies_per_day": copies_per_day,
        "reserve_gib": reserve_gib,
        "safety_cycles": safety_cycles,
        "free_bytes": available_bytes,
        "additional_archive_bytes": required_growth,
        "transient_slack_bytes": transient_slack,
        "reserve_bytes": reserve_bytes,
        "required_free_bytes": required_bytes,
        "deficit_bytes": shortage_bytes,
        "instances": projections,
        "caveat": "Sizing uses existing archive sizes and cannot predict world growth, compression changes or other filesystem consumers.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--instance", action="append", required=True,
                        help="Controller instance ID (repeat as needed)")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--copies-per-day", type=int, default=1)
    parser.add_argument("--reserve-gib", type=int, default=20)
    parser.add_argument("--safety-cycles", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        result = forecast(
            args.backup_root, args.instance, days=args.days,
            copies_per_day=args.copies_per_day, reserve_gib=args.reserve_gib,
            safety_cycles=args.safety_cycles,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked_invalid_evidence", "reason": str(exc)}))
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
