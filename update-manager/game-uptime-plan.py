#!/usr/bin/env python3
"""Read-only, fail-closed DSM update impact analysis.

This is diagnostic only: it never authorizes a no-drain update.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXCLUDE_TOP = frozenset({"instances", "game-data", "logs", ".git"})
EXCLUDE_PREFIX = ("runtime/hybrid-agent-state/", "runtime/hybrid-instance-storage/")
EXCLUDE_EXACT = frozenset({"config/dsm.conf"})
# This deliberately tiny allowlist does NOT yet authorize a live update.
COSMETIC_PREFIX = ("docs/", "release/RELEASE_NOTES_", "dashboard/web/")
COSMETIC_EXACT = frozenset({"version"})


def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("unsafe or missing DSM root")
    files: dict[str, tuple[int, str]] = {}
    for entry in root.rglob("*"):
        rel = entry.relative_to(root).as_posix()
        if rel.split("/", 1)[0] in EXCLUDE_TOP or any(
            rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in EXCLUDE_PREFIX
        ) or rel in EXCLUDE_EXACT:
            continue
        if entry.is_symlink():
            raise ValueError(f"symlink in release impact inventory: {rel}")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError(f"unsafe release filesystem entry: {rel}")
        digest = hashlib.sha256()
        with entry.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        files[rel] = (entry.stat().st_mode & 0o777, digest.hexdigest())
    return files


def analyze(installed: Path, target: Path) -> dict[str, object]:
    before = _inventory(installed)
    after = _inventory(target)
    changed = sorted(name for name in before.keys() | after.keys()
                     if before.get(name) != after.get(name))
    safety_sensitive = [
        name for name in changed
        if name not in COSMETIC_EXACT
        and not any(name.startswith(prefix) for prefix in COSMETIC_PREFIX)
    ]
    return {
        "kind": "CapivaraDSMGameUptimeImpact",
        "schema_version": 1,
        "mode": "read_only_diagnostic",
        "changed_count": len(changed),
        "critical_changed_count": len(safety_sensitive),
        "requires_game_drain": bool(safety_sensitive),
        "live_no_drain_authorized": False,
        "classification": "maintenance_required" if safety_sensitive else "review_only",
        "critical_files": safety_sensitive[:60],
        "changes_truncated": len(safety_sensitive) > 60,
        "reason": (
            "Runtime, updater, systemd or other non-allowlisted files changed; "
            "retain current fail-closed game drain."
            if safety_sensitive else
            "Only limited presentation/version files changed. An independent "
            "systemd/process compatibility gate is still required before no-drain use."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installed", type=Path)
    parser.add_argument("target", type=Path)
    arguments = parser.parse_args()
    try:
        result = analyze(arguments.installed, arguments.target)
    except (OSError, ValueError) as exc:
        result = {
            "kind": "CapivaraDSMGameUptimeImpact",
            "classification": "blocked",
            "requires_game_drain": True,
            "live_no_drain_authorized": False,
            "error": str(exc)[:300],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
