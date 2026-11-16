#!/usr/bin/env python3
"""#1033: bounded, local, READ-ONLY backup/record reconciliation.

Usage: python3 tools/backup_history_dry_run.py --instance-id ... \
  --backup-root /var/lib/capivara-agent/backups \
  --results-root /var/lib/capivara-agent/backup-results

Never unlinks, repairs, extracts, hashes large files, starts games, or queues
deletions. A physical inventory is not equivalent to a complete restore test.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "database"))
from backup_history_projection import annotate_backup_jobs, complete_record

_ID = re.compile(r"[a-zA-Z0-9._-]{1,191}\Z")
MAX_ENTRIES = 20_000
SMALL_ARCHIVE_BYTES = 256 * 1024
MANIFEST = ".capivara-backup-manifest.json"


def _scan_directory(base: Path, instance_id: str):
    if not _ID.fullmatch(instance_id) or instance_id in {".", ".."}:
        raise ValueError("invalid backup instance ID")
    if base.is_symlink() or not base.is_dir():
        raise OSError("backup root not accessible or unsafe")
    directory = base / instance_id
    if directory.is_symlink():
        raise OSError("backup instance directory is a symlink")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise OSError("backup instance directory is not a directory")
    records = []
    with os.scandir(directory) as it:
        for entry in it:
            if len(records) >= MAX_ENTRIES:
                raise OSError("backup inventory limit exceeded")
            item = entry.stat(follow_symlinks=False)
            if (not stat.S_ISREG(item.st_mode) or item.st_nlink > 1):
                raise OSError("ambiguous or unsafe backup inventory entry")
            path = Path(entry.path)
            name = path.name
            if name.endswith(".tar.gz"):
                backup_id = name[:-7]
            elif name.endswith(".tgz"):
                backup_id = name[:-4]
            elif name.endswith(".tar"):
                backup_id = name[:-4]
            else:
                backup_id = None
            kind = "unclassified_file" if backup_id is None else "archive_unverified"
            if backup_id and item.st_size <= SMALL_ARCHIVE_BYTES:
                try:
                    with tarfile.open(path, "r:*") as archive:
                        members = archive.getmembers()
                        if not any(m.isfile() and m.name != MANIFEST for m in members):
                            kind = "manifest_only"
                except (OSError, tarfile.TarError, ValueError, EOFError):
                    kind = "invalid_archive"
            records.append({
                "filename": name,
                "backup_id": backup_id,
                "bytes": item.st_size,
                "modified_ns": item.st_mtime_ns,
                "kind": kind,
                "full_integrity_verified": False,
            })
    return sorted(records, key=lambda row: (row["filename"], row["modified_ns"]))


def _read_local_reports(base: Path, instance_id: str):
    if base.is_symlink():
        raise OSError("backup result root is a symlink")
    if not base.exists():
        return []
    if not base.is_dir():
        raise OSError("backup result root is inaccessible")
    reports = []
    scanned = 0
    with os.scandir(base) as it:
        for entry in it:
            scanned += 1
            if scanned > MAX_ENTRIES:
                raise OSError("backup results scan limit exceeded")
            if not entry.name.endswith(".json"):
                continue
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise OSError("unsafe backup result")
            # Bounded JSON parser, never read arbitrary-sized result records.
            if info.st_size > 256 * 1024:
                raise OSError("backup result exceeds size limit")
            try:
                value = json.loads(Path(entry.path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            if isinstance(value, dict) and str(value.get("instance_id") or "") == instance_id:
                reports.append(value)
    return reports


def _timestamp(row: dict):
    return str(row.get("completed_at") or row.get("created_at") or row.get("started_at") or "")


def reconcile(backup_root: Path, results_root: Path, instance_id: str) -> dict:
    """Returns a non-destructive report; no cleanup candidates are emitted."""
    if not _ID.fullmatch(instance_id) or instance_id in {".", ".."}:
        raise ValueError("invalid backup instance ID")
    files = _scan_directory(backup_root, instance_id)
    reports = _read_local_reports(results_root, instance_id)
    by_id: dict[str, list[dict]] = {}
    for report in reports:
        if report.get("action") == "create" and report.get("status") == "completed":
            bid = str(report.get("backup_id") or "")
            if bid:
                by_id.setdefault(bid, []).append(report)
    annotated = annotate_backup_jobs(sorted(reports, key=_timestamp, reverse=True))
    operational_ids = {str(x.get("backup_id")) for x in annotated if x.get("history_role") == "operational_reference"}
    indexed = set()
    for item in files:
        bid = item.get("backup_id")
        matches = by_id.get(str(bid), []) if bid else []
        if not bid or not matches:
            item["record_status"] = "not_in_local_results"
        elif len(matches) != 1:
            item["record_status"] = "conflicting_local_results"
        else:
            record = matches[0]
            indexed.add(str(bid))
            if not complete_record(record):
                item["record_status"] = "incomplete_record"
            elif int(record["size_bytes"]) != item["bytes"]:
                item["record_status"] = "size_mismatch"
            elif Path(str(record["artifact_path"])).name != item["filename"]:
                item["record_status"] = "path_mismatch"
            elif item["kind"] in {"manifest_only", "invalid_archive"}:
                item["record_status"] = "unrestorable_or_invalid"
            elif bid in operational_ids:
                item["record_status"] = "operational_record_unverified"
            else:
                item["record_status"] = "historical_record_unverified"
        # Regardless of classification, NO file is eligible for removal.
        item["disposition"] = "preserve"
    disk_backups = {str(x.get("backup_id") or "") for x in files}
    missing = sorted(bid for bid in by_id if bid not in disk_backups)
    kinds = {}
    for item in files:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    return {
        "schema_version": 1,
        "kind": "CapivaraBackupHistoryDryRun",
        "instance_id": instance_id,
        "dry_run": True,
        "status": "review_required",
        "automatic_deletion_authorized": False,
        "physical_files": files,
        "physical_bytes": sum(x["bytes"] for x in files),
        "physical_file_count": len(files),
        "classifications": kinds,
        "completed_local_records": sum(len(x) for x in by_id.values()),
        "missing_registered_backup_ids": missing,
        "unmatched_local_result_count": sum(x["record_status"] == "not_in_local_results" for x in files),
        "physical_integrity_verified": False,
        "proposed_delete_count": 0,
        "proposed_actions": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only history reconciliation for one instance")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = reconcile(args.backup_root, args.results_root, args.instance_id)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"dry_run": True, "status": "blocked", "reason": str(exc),
                          "proposed_actions": [], "proposed_delete_count": 0}))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
