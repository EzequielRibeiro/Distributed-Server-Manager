#!/usr/bin/env python3
"""Read-only, root-owned DSM maintenance hold for reconciliation loops (#928).

This file is deliberately NOT a live no-drain authorization or an updater.
Until a durable transaction owner and authenticated multi-host handshake exist,
no DSM production code creates or clears the marker. When an operator-owned
marker exists, local Agent/Hybrid reconciler loops must fail closed, including
on damaged or expired evidence. Absence preserves current runtime behavior.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time

HOLD_PATH = Path("/run/capivara-dsm/no-drain-maintenance.json")
_KIND = "CapivaraDSMNoDrainMaintenanceHold"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_KEYS = frozenset({"kind", "schema_version", "transaction_id",
                   "issued_at", "expires_at"})


def observe(*, path: Path = HOLD_PATH, trusted_uid: int = 0,
            now: int | None = None) -> dict[str, object]:
    """Return an unforgeable-by-unprivileged-users local hold observation.

    An invalid, unreadable, expired or forged marker remains an ACTIVE block
    requiring manual review. The reader never changes or deletes a marker.
    The optional path/trusted_uid inputs are for isolated tests, not runtime
    configuration; Agent and Worker always use the fixed root-owned path.
    """
    root = Path(path)
    try:
        parent = root.parent.lstat()
    except FileNotFoundError:
        return {"active": False, "reason": "hold_directory_absent"}
    except OSError:
        return {"active": True, "reason": "hold_directory_unreadable"}
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != trusted_uid
            or parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        return {"active": True, "reason": "hold_directory_untrusted"}

    try:
        before = root.lstat()
    except FileNotFoundError:
        return {"active": False, "reason": "hold_absent"}
    except OSError:
        return {"active": True, "reason": "hold_unreadable"}

    if (not stat.S_ISREG(before.st_mode) or before.st_uid != trusted_uid
            or before.st_nlink != 1
            or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or before.st_size <= 0 or before.st_size > 2048):
        return {"active": True, "reason": "hold_file_untrusted"}

    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        fd = os.open(root, flags)
        with os.fdopen(fd, "rb") as stream:
            observed = os.fstat(stream.fileno())
            if (observed.st_dev != before.st_dev or observed.st_ino != before.st_ino
                    or observed.st_size != before.st_size
                    or not stat.S_ISREG(observed.st_mode)):
                return {"active": True, "reason": "hold_file_changed"}
            data = stream.read(2049)
        if len(data) > 2048:
            raise ValueError("oversized hold")
        payload = json.loads(data)
    except (OSError, ValueError, UnicodeError, TypeError):
        return {"active": True, "reason": "hold_evidence_invalid"}

    if (not isinstance(payload, dict) or set(payload) != _KEYS
            or payload.get("kind") != _KIND
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or not isinstance(payload.get("transaction_id"), str)
            or not _ID.fullmatch(payload["transaction_id"])
            or type(payload.get("issued_at")) is not int
            or type(payload.get("expires_at")) is not int):
        return {"active": True, "reason": "hold_contract_invalid"}
    current = int(time.time()) if now is None else now
    started, expires = payload["issued_at"], payload["expires_at"]
    if (started <= 0 or started > current + 30 or
            expires <= started or expires - started > 900):
        return {"active": True, "reason": "hold_window_invalid"}
    if current >= expires:
        return {"active": True, "reason": "hold_expired_requires_operator"}
    return {"active": True, "reason": "root_owned_maintenance_hold"}

if __name__ == "__main__":
    # A read-only check used by scheduler_worker.sh. An active, malformed,
    # expired or unsafe hold exits nonzero and prevents that tick.
    raise SystemExit(2 if observe()["active"] else 0)
