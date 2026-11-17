"""Read-only, bounded evidence for the DayZ Linux 1.30 messages.xml issue.

This is only an advisory. A 'No Shutdown message present' log entry is not
proof of the root cause and MUST NOT authorize a stop, kill or restart.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_VERSION = re.compile(r"^(?:Version|DayZ Console version \(64bit\))\s+(1\.30\.164289(?:\.\d+)?)", re.MULTILINE)
_SIGNATURE = "No Shutdown message present"
_MAX_BOOT_LOG_BYTES = 256 * 1024


def suspected_linux_130_messages_issue(record: dict[str, Any]) -> dict[str, str] | None:
    """Inspect only the beginning of the newest instance-private DayZ RPT.

    Do not follow symlinks or inspect shared/untrusted paths. The result is
    informational; it does not prove countdown support or authorize actions.
    """
    root = str(record.get("files_root") or "").strip()
    arguments = record.get("arguments") or ()
    if not root or not isinstance(arguments, (list, tuple)):
        return None
    profile_args = [str(arg).split("=", 1)[1] for arg in arguments
                    if str(arg).lower().startswith("-profiles=")]
    if len(profile_args) != 1:
        return None
    try:
        private = Path(root).resolve(strict=True)
        raw = Path(profile_args[0])
        profile = (raw if raw.is_absolute() else private / raw).resolve(strict=True)
        profile.relative_to(private)
        if not profile.is_dir():
            return None
        reports = sorted((f for f in profile.glob("DayZServer_*.RPT")
                          if f.is_file() and not f.is_symlink()),
                         key=lambda f: f.stat().st_mtime, reverse=True)
        if not reports:
            return None
        latest = reports[0]
        latest.resolve(strict=True).relative_to(private)
        with latest.open("rb") as source:
            boot = source.read(_MAX_BOOT_LOG_BYTES).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    version = _VERSION.search(boot)
    if not version or _SIGNATURE not in boot:
        return None
    return {
        "code": "dayz_linux_130_messages_xml_suspected",
        "version": version.group(1),
        "evidence": _SIGNATURE,
        "upstream_issue": "DZG-2653",
    }
