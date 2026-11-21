#!/usr/bin/env python3
"""Read-only, fail-closed DSM update impact analysis.

This is diagnostic only: it never authorizes a no-drain update.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

# SteamCMD creates user-home caches under the installed tree on some hosts.
# They are preserved runtime data, not DSM release payload. Never traverse them.
EXCLUDE_TOP = frozenset({"instances", "game-data", "logs", ".git", ".steam", ".local"})
EXCLUDE_PREFIX = ("runtime/hybrid-agent-state/", "runtime/hybrid-instance-storage/",
                  "runtime/state/", "runtime/artifact-transfers/")
EXCLUDE_EXACT = frozenset({"config/dsm.conf"})
# This deliberately tiny allowlist does NOT yet authorize a live update.
COSMETIC_PREFIX = ("docs/", "release/RELEASE_NOTES_", "dashboard/web/")
COSMETIC_EXACT = frozenset({"version"})



# More granular, *advisory* classification for #928. This is deliberately
# independent of the legacy drain boolean: not even a "restart_free" candidate
# grants permission for live no-drain updates.
CHANGE_TIERS = ("no_change", "restart_free", "control_plane_restart_candidate",
                "instance_maintenance_required", "full_maintenance_required")
CONTROL_PLANE_PREFIXES = (
    "dashboard/", "api/", "scheduler/", "notification/", "metrics/", "monitor/",
)
CONTROL_PLANE_SUFFIXES = frozenset((
    ".py", ".js", ".css", ".html", ".htm", ".json", ".svg", ".png", ".ico",
    ".woff", ".woff2", ".map",
))
INSTANCE_PREFIXES = ("agents/", "games/", "catalog/", "player/", "packages/")


def _change_tier(name: str, before: dict, after: dict) -> str:
    old, new = before.get(name), after.get(name)
    # Any mode change, suspicious file permissions, or removal/addition of
    # runtime code needs a maintenance window. Documentation-only additions
    # are fine, but never executable documentation disguised as release notes.
    if old is not None and new is not None and old[0] != new[0]:
        return "full_maintenance_required"
    info = new if new is not None else old
    if info is None or info[0] & 0o022:
        return "full_maintenance_required"
    is_doc = (
        name == "version" and old is not None and new is not None
        or name.startswith("docs/") and Path(name).suffix.lower() in (".md", ".txt", ".rst")
        or name.startswith("release/RELEASE_NOTES_") and name.endswith(".md")
    )
    if is_doc and not info[0] & 0o111:
        return "restart_free"
    if (old is not None and new is not None
            and any(name.startswith(prefix) for prefix in CONTROL_PLANE_PREFIXES)
            and Path(name).suffix.lower() in CONTROL_PLANE_SUFFIXES
            and not info[0] & 0o111):
        return "control_plane_restart_candidate"
    if any(name.startswith(prefix) for prefix in INSTANCE_PREFIXES):
        return "instance_maintenance_required"
    return "full_maintenance_required"


def _tiers(changed: list[str], before: dict, after: dict) -> dict[str, object]:
    counts = {tier: 0 for tier in CHANGE_TIERS if tier != "no_change"}
    examples = {tier: [] for tier in counts}
    for name in changed:
        tier = _change_tier(name, before, after)
        counts[tier] += 1
        if len(examples[tier]) < 12:
            examples[tier].append(name)
    highest = next((tier for tier in reversed(CHANGE_TIERS[1:])
                    if counts[tier]), "no_change")
    # These are advisory classes only. Independent process/contract proof,
    # durable rollback and a separately reviewed live path are still missing.
    return {
        "change_tier": highest,
        "change_tier_counts": counts,
        "change_tier_examples": examples,
        "control_plane_candidate_for_disposable_review":
            bool(changed) and highest in (
                "restart_free", "control_plane_restart_candidate"),
        "live_no_drain_authorized": False,
    }



def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("unsafe or missing DSM root")
    files: dict[str, tuple[int, str]] = {}
    # Prune preserved runtime trees BEFORE descending into them. A post-rglob
    # exclusion still walks huge live game worlds and SteamCMD caches.
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        parent = Path(current)
        def excluded(entry: Path) -> bool:
            rel = entry.relative_to(root).as_posix()
            return (rel.split("/", 1)[0] in EXCLUDE_TOP or
                    any(rel == prefix.rstrip("/") or rel.startswith(prefix)
                        for prefix in EXCLUDE_PREFIX) or rel in EXCLUDE_EXACT)
        for dirname in list(dirs):
            entry = parent / dirname
            if excluded(entry):
                dirs.remove(dirname)
            elif entry.is_symlink():
                raise ValueError(f"symlink in release impact inventory: {entry.relative_to(root)}")
        for name in names:
            entry = parent / name
            if excluded(entry):
                continue
            rel = entry.relative_to(root).as_posix()
            if entry.is_symlink():
                raise ValueError(f"symlink in release impact inventory: {rel}")
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
    tiers = _tiers(changed, before, after)
    return {
        **tiers,
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
