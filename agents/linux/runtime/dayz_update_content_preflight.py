#!/usr/bin/env python3
"""Read-only DayZ DLC discovery preflight shared by both update entry points.

This is diagnostic evidence, not an authorization to mutate shared game data.
A warning must not cause a recursive chown or disable signature verification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .content_discovery_audit import audit_dayz_dlc_roots
except ImportError:
    from content_discovery_audit import audit_dayz_dlc_roots


def inspect_update_content_preflight(
    staging: Path, game: str, *, runtime_user: str = "capivara-instance"
) -> dict[str, Any] | None:
    """Report DLC owner consistency after install, before activation."""
    if str(game).strip().lower() != "dayz":
        return None
    report = audit_dayz_dlc_roots(Path(staging), runtime_user=runtime_user)
    roots = report.get("roots") or []
    return {
        "status": report.get("status", "unknown"),
        "reason": report.get("reason"),
        "runtime_user": runtime_user,
        "dlc_package_count": sum(int(item.get("packages", 0)) for item in roots),
        "dlc_roots": [
            {
                "directory": item["directory"],
                "packages": item["packages"],
                "ownership_warning": (
                    not item.get("owner_matches_runner", False)
                    or not item.get("addons_owner_matches_runner", False)
                    or bool(item.get("package_owner_mismatch_count", 0))
                ),
            }
            for item in roots
        ],
        "requires_review": report.get("status") != "ok",
        "read_only": True,
        "repair_performed": False,
    }


__all__ = ["inspect_update_content_preflight"]
