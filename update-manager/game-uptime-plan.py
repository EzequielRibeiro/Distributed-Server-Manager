#!/usr/bin/env python3
"""Read-only, fail-closed DSM update impact analysis.

This is diagnostic only: it never authorizes a no-drain update.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
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


# These are bootstrap components: an older installed tree cannot be
# assumed to honor a fence supplied by the candidate that replaces it.
_BOOTSTRAP = (
    "update-manager/game-uptime-file-transaction.py",
    "update-manager/game-uptime-local-scope-lease.py",
    "agents/linux/runtime/game_uptime_hold_coordinator.py",
    "agents/linux/runtime/game_uptime_ssh_transport.py",
    "agents/linux/runtime/game_uptime_privileged_flock.py",
    "agents/linux/runtime/game_uptime_finalization_flock.py",
    "dashboard/game_uptime_controller_mutation_gate.py",
    "dashboard/workers/maintenance_hold_gate.py",
    "systemd/dsm-dashboard.service",
    "systemd/dsm-dashboard-worker.service",
)


def _fixed_file_plan(installed, target, before, after, changed):
    """Exact candidate for the actual bounded file engine; never an ACK.

    Keep the existing advisory classifier unchanged. The fixed-file engine
    is deliberately narrower: no additions/removals, no arbitrary changes
    to docs or runtime state and no changes to the updater that owns it.
    Metadata may change only alongside compatible existing product files.
    """
    loader = SourceFileLoader("dsm928_fixed_file_plan_engine",
                              str(Path(__file__).with_name("game-uptime-file-transaction.py")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    engine = importlib.util.module_from_spec(spec)
    loader.exec_module(engine)
    bootstrap = [name for name in _BOOTSTRAP
                 if name in after and before.get(name) != after[name]]
    blocked = []
    entries = []
    encoded_size = 0
    for name in changed:
        old, new = before.get(name), after.get(name)
        if name in bootstrap:
            reason = "bootstrap_component_changed"
        elif old is None or new is None:
            reason = "addition_or_removal"
        elif old[0] != new[0] or old[0] & 0o7133:
            reason = "incompatible_file_mode"
        elif not engine._approved_path(name):
            reason = "outside_fixed_file_engine"
        else:
            sizes = [(root / name).lstat().st_size for root in (installed, target)]
            if max(sizes) > engine._LIMIT:
                reason = "file_exceeds_engine_limit"
            else:
                encoded_size += sum(4 * ((size + 2) // 3) for size in sizes)
                entries.append(name)
                continue
        blocked.append({"path": name, "reason": reason})
    reasons = []
    if bootstrap:
        reasons.append("initial_fence_aware_installation_or_bootstrap_update_required")
    if blocked:
        reasons.append("incompatible_product_changes")
    if len(entries) > engine._COUNT or encoded_size > engine._TOTAL - 1048576:
        reasons.append("fixed_file_transaction_capacity_exceeded")
    if not changed:
        reasons.append("no_product_changes")
    eligible = not reasons
    exact_plan = sorted(entries, key=lambda name: (name in engine._METADATA, name))
    # Never hand off a partial or truncated plan to an executor.
    return {"status": ("compatible_file_plan_only" if eligible else "blocked"),
            "bootstrap_installation_required": bool(bootstrap),
            "bootstrap_components_changed": bootstrap,
            "file_count": len(entries),
            "changed_paths": exact_plan if eligible else [],
            "incompatible_file_count": len(blocked),
            "incompatible_examples": blocked[:40],
            "blockers": reasons,
            "live_no_drain_authorized": False}


def analyze(installed: Path, target: Path) -> dict[str, object]:
    before = _inventory(installed)
    after = _inventory(target)
    changed = sorted(name for name in before.keys() | after.keys()
                     if before.get(name) != after.get(name))
    # Separate byte changes from permission drift without relaxing any
    # existing admission rule. Generated bytecode is reported, not exempted:
    # an untrusted cache may still contain executable code.
    differences = {
        "added": sum(name not in before for name in changed),
        "removed": sum(name not in after for name in changed),
        "content_changed": sum(name in before and name in after
                               and before[name][1] != after[name][1] for name in changed),
        "mode_only": sum(name in before and name in after
                         and before[name][1] == after[name][1] for name in changed),
        "python_cache_paths": sum("__pycache__" in Path(name).parts
                                  or Path(name).suffix in (".pyc", ".pyo")
                                  for name in changed),
    }
    safety_sensitive = [
        name for name in changed
        if name not in COSMETIC_EXACT
        and not any(name.startswith(prefix) for prefix in COSMETIC_PREFIX)
    ]
    tiers = _tiers(changed, before, after)
    fixed = _fixed_file_plan(installed, target, before, after, changed)
    return {
        **tiers,
        "fixed_file_transaction_plan": fixed,
        "kind": "CapivaraDSMGameUptimeImpact",
        "schema_version": 1,
        "mode": "read_only_diagnostic",
        "changed_count": len(changed),
        "difference_counts": differences,
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
