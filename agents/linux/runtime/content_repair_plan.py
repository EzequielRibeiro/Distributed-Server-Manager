#!/usr/bin/env python3
"""Non-executable DayZ DLC ownership review plan (issue #977).

This is deliberately not a repair executor. Report ownership discrepancies in
known DLCs; an administrator must choose and separately validate a policy.
"""
from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

try:
    from .content_discovery_audit import audit_dayz_dlc_roots, KNOWN_DAYZ_DLC_ROOTS, MAX_ADDON_ENTRIES
except ImportError:
    from content_discovery_audit import audit_dayz_dlc_roots, KNOWN_DAYZ_DLC_ROOTS, MAX_ADDON_ENTRIES

MAX_PLAN_ENTRIES = 8192


def plan_dayz_dlc_ownership(root: Path, *, runtime_user: str = "capivara-instance",
                            expected_uid: int | None = None) -> dict[str, Any]:
    """Return metadata-only candidates. No chmod, chown, ACL or command strings."""
    audit = audit_dayz_dlc_roots(root, runtime_user=runtime_user, expected_uid=expected_uid)
    result: dict[str, Any] = {
        "schema_version": 1, "kind": "DayZContentOwnershipReview",
        "mode": "dry-run", "executable": False, "read_only": True,
        "audit_status": audit["status"], "audit_reason": audit.get("reason"),
        "candidates": [], "requires_manual_validation": True,
    }
    if audit["status"] not in {"ok", "warning"}:
        result["status"] = "blocked"
        return result
    uid = audit["expected_uid"]
    root = Path(root)
    candidates: list[dict[str, Any]] = []
    # Metadata snapshots reduce false review plans during concurrent updates.
    # They are NOT a lock or authority to execute filesystem mutations.
    observed: list[tuple[Path, tuple[int, int, int, int, int, int, int]]] = []

    def observe(path: Path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeError("unsafe_link")
        observed.append((path, (
            info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns,
        )))
        return info

    try:
        root_info = observe(root)
        if not stat.S_ISDIR(root_info.st_mode):
            raise RuntimeError("unsafe_root")
        for finding in audit["roots"]:
            name = finding["directory"]
            # Explicit fail-closed allowlist; do not treat arbitrary game/mod
            # folders as candidate paths for privileged remediation.
            if name.lower() not in KNOWN_DAYZ_DLC_ROOTS or name in (".", ".."):
                result["status"] = "blocked"
                result["reason"] = "unrecognized_dlc_root"
                result["candidates"] = []
                return result
            directory = root / name
            addons = directory / "addons"
            entries = [directory, addons]
            package_count = 0
            for entry in addons.iterdir():
                if entry.suffix.lower() not in {".pbo", ".ebo"}:
                    continue
                packages_stat = entry.lstat()
                if not stat.S_ISREG(packages_stat.st_mode):
                    result["status"] = "blocked"
                    result["reason"] = "non_regular_package"
                    result["candidates"] = []
                    return result
                entries.append(entry)
                package_count += 1
                if package_count > MAX_ADDON_ENTRIES:
                    raise RuntimeError("addon_entry_limit")
            for entry in entries:
                meta = observe(entry)
                if entry in (directory, addons):
                    if not stat.S_ISDIR(meta.st_mode):
                        raise RuntimeError("unsafe_directory")
                elif not stat.S_ISREG(meta.st_mode):
                    raise RuntimeError("unsafe_package")
                if meta.st_uid != uid:
                    if len(candidates) >= MAX_PLAN_ENTRIES:
                        raise RuntimeError("plan_limit")
                    candidates.append({
                        "relative_path": entry.relative_to(root).as_posix(),
                        "current_uid": meta.st_uid,
                        "current_gid": meta.st_gid,
                        "current_mode": oct(stat.S_IMODE(meta.st_mode)),
                        "expected_uid": uid,
                        "issue": "ownership_mismatch",
                    })
        # A second inventory detects common concurrent SteamCMD modifications.
        # Even when this agrees, a future executor MUST re-open by descriptor,
        # validate identity under an exclusive update lock, and roll back safely.
        second = audit_dayz_dlc_roots(root, runtime_user=runtime_user, expected_uid=uid)
        if second != audit:
            raise RuntimeError("inventory_changed")
        for path, fingerprint in observed:
            info = path.lstat()
            current = (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                       info.st_gid, info.st_size, info.st_mtime_ns)
            if current != fingerprint:
                raise RuntimeError("entry_changed")
    except (OSError, RuntimeError, ValueError):
        result["status"] = "blocked"
        result["reason"] = "filesystem_changed_or_unsafe"
        result["candidates"] = []
        return result
    result["candidates"] = candidates
    result["status"] = "review_required" if candidates else "no_owner_mismatch"
    return result


__all__ = ["MAX_PLAN_ENTRIES", "plan_dayz_dlc_ownership"]
