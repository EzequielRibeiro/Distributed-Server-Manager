"""Read-only representation of operational and historical backup jobs.

A SHA-256 stored in a completed job is evidence of a recorded check, not
proof that the physical TAR still exists or remains byte-for-byte valid.
Never infer a cleanup authorization from this projection.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")


def complete_record(job: dict[str, Any]) -> bool:
    size = job.get("size_bytes")
    digest = job.get("sha256")
    return (
        str(job.get("action") or "").lower() == "create"
        and str(job.get("status") or "").lower() == "completed"
        and bool(str(job.get("backup_id") or "").strip())
        and isinstance(digest, str)
        and _SHA256.fullmatch(digest) is not None
        and type(size) is int
        and size > 0
        and bool(str(job.get("artifact_path") or "").strip())
    )


def annotate_backup_jobs(jobs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decorate existing DB rows without hiding failures or altering jobs.

    DB returns descending created_at; pick newest completed, check-summed
    *record* as the operational reference and show older rows as history.
    Physical validity remains UNKNOWN for every result in this function.
    """
    rows = [dict(row) for row in jobs]
    # Deduplicate ambiguous history IDs conservatively; never promote them.
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("action") == "create" and row.get("status") == "completed":
            bid = str(row.get("backup_id") or "")
            if bid:
                counts[bid] = counts.get(bid, 0) + 1

    selected_id = None
    for row in rows:
        if complete_record(row) and counts.get(str(row.get("backup_id")), 0) == 1:
            selected_id = str(row["backup_id"])
            break

    for row in rows:
        if row.get("action") != "create":
            continue
        if row.get("status") != "completed":
            row["history_role"] = "operation_not_completed"
        elif counts.get(str(row.get("backup_id") or ""), 0) > 1:
            row["history_role"] = "ambiguous_record"
        elif not complete_record(row):
            row["history_role"] = "incomplete_record"
        elif str(row.get("backup_id")) == selected_id:
            row["history_role"] = "operational_reference"
        else:
            row["history_role"] = "historical_record"
        row["physical_verification"] = "not_checked"
        row["retention_protection"] = "preserve"
    return rows
