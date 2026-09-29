#!/usr/bin/env python3
"""Bound abandoned customer uploads without ever touching active transfer files.

Runs out-of-process in dsm-dashboard-worker (not the HTTP Dashboard). The
watchdog is deliberately conservative: if a writer cannot be ruled out, skip.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[2])).resolve()
for location in (ROOT, ROOT / "database", ROOT / "dashboard" / "workers"):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

from artifact_transfer_repository import ArtifactTransferRepository
from hybrid_agent_worker import _database_environment
from runtime_backend import backend_from_environment

INTERVAL_SECONDS = max(60, min(int(os.environ.get("DSM_UPLOAD_WATCHDOG_SECONDS", "300")), 3600))
STAGING_MINUTES = max(30, min(int(os.environ.get("DSM_UPLOAD_STAGING_TIMEOUT_MINUTES", "60")), 1440))
FINAL_MINUTES = max(5, min(int(os.environ.get("DSM_UPLOAD_FAILED_RETENTION_MINUTES", "15")), 1440))
BATCH_SIZE = max(1, min(int(os.environ.get("DSM_UPLOAD_WATCHDOG_BATCH_SIZE", "100")), 500))


def _date(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _unopened(path: Path) -> bool:
    """A missing fuser, unusual return code, or a writer means DO NOT DELETE."""
    if not path.exists():
        return True
    if path.is_symlink() or not path.is_file() or not shutil.which("fuser"):
        return False
    try:
        result = subprocess.run(
            ["fuser", "-s", "--", str(path)], capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 1  # 0=open, 1=no owner, other=indeterminate


def _owned_paths(repo, item):
    tid = repo._token(item["transfer_id"], "transfer_id")
    name = str(item.get("filename") or "")
    if not name or name != Path(name).name or name in {".", ".."}:
        return None
    directory = repo.spool / tid
    if directory.is_symlink() or directory.resolve() != directory:
        return None
    artifact = directory / name
    part = artifact.with_suffix(artifact.suffix + ".part")
    if artifact.is_symlink() or part.is_symlink():
        return None
    pointer = str(item.get("controller_path") or "")
    if pointer and Path(pointer) != artifact:
        return None
    return artifact, part, directory


def sweep(repo: ArtifactTransferRepository, *, now: datetime | None = None, limit: int = BATCH_SIZE):
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stage_cutoff = instant - timedelta(minutes=STAGING_MINUTES)
    final_cutoff = instant - timedelta(minutes=FINAL_MINUTES)
    ph = repo.dialect.placeholder
    with repo.session() as session:
        rows = session.execute(
            "SELECT transfer_id,filename,controller_path,status,updated_at "
            "FROM artifact_transfers WHERE purpose='content_upload' "
            "AND direction='controller_to_agent' "
            "AND status IN ('staging','failed','cancelled') "
            f"ORDER BY updated_at ASC LIMIT {max(1, min(int(limit), 500))}",
        ).fetchall()
    report = {"inspected": 0, "marked_failed": 0, "files_removed": 0, "skipped": 0}
    for item in (dict(row) for row in rows):
        report["inspected"] += 1
        stamp = _date(item.get("updated_at"))
        status = str(item.get("status") or "")
        cutoff = stage_cutoff if status == "staging" else final_cutoff
        if stamp is None or stamp >= cutoff:
            report["skipped"] += 1
            continue
        paths = _owned_paths(repo, item)
        if paths is None:
            report["skipped"] += 1
            continue
        artifact, part, directory = paths
        # Never expire a staging transfer with a complete archive on disk.
        if status == "staging" and artifact.exists():
            report["skipped"] += 1
            continue
        candidates = [p for p in (artifact, part) if p.exists()]
        if any(p.is_symlink() or not p.is_file() or
               datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) >= cutoff or
               not _unopened(p) for p in candidates):
            report["skipped"] += 1
            continue
        latest = repo.get(item["transfer_id"])
        if latest.get("status") != status or _date(latest.get("updated_at")) != stamp:
            report["skipped"] += 1
            continue
        if status == "staging":
            changed = repo.fail_staging_upload(
                item["transfer_id"], "Upload interrompido: transferência incompleta e inativa.",
            )
            if changed.get("status") != "failed":
                report["skipped"] += 1
                continue
            report["marked_failed"] += 1
        # Recheck that nothing re-opened a file. Missing 'fuser' is fail-closed.
        if any(not _unopened(p) for p in candidates):
            report["skipped"] += 1
            continue
        for path in candidates:
            try:
                path.unlink(missing_ok=True)
                report["files_removed"] += 1
            except OSError:
                report["skipped"] += 1
        try:
            directory.rmdir()
        except OSError:
            pass
    return report


def run_forever():
    backend = backend_from_environment(_database_environment(ROOT))
    repo = ArtifactTransferRepository(backend, ROOT)
    repo.initialize()
    while True:
        try:
            report = sweep(repo)
            if report["marked_failed"] or report["files_removed"]:
                print("upload retention " + " ".join(f"{k}={v}" for k, v in report.items()), flush=True)
        except Exception as exc:
            print(f"upload retention failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    run_forever()
