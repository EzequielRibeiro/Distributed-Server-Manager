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
import re
import stat
import struct
import sys

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



# Controller/legacy runtime projection JSONs, not executable product files.
# Only unsigned installed projections at the documented exact depth can be
# omitted; a matching member of either signed release remains product data.
_PROJECTION_NAMES = frozenset({
    "server.json", "instance.json", "runtime.json", "provision.json",
    "mods.json", "metrics.json", "events.json", "backup.json", "doctor.json",
})


def _unsigned_runtime_projection(relative, signed_paths):
    if signed_paths is None or relative in signed_paths:
        return False
    parts = relative.split("/")
    return (len(parts) == 6 and parts[:2] == ["runtime", "resources"]
            and parts[-1] in _PROJECTION_NAMES
            and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
                    for value in parts[2:5]))


def _inventory(root: Path, *, signed_paths=None) -> dict[str, tuple[int, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("unsafe or missing DSM root")
    files: dict[str, tuple[int, str]] = {}
    # Prune preserved runtime trees BEFORE descending into them. A post-rglob
    # exclusion still walks huge live game worlds and SteamCMD caches.
    def walk_error(exc):
        raise exc
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False,
                                        onerror=walk_error):
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
            projection = _unsigned_runtime_projection(rel, signed_paths)
            try:
                named = entry.lstat()
            except FileNotFoundError:
                if projection:
                    # A generated observation may disappear between listing
                    # and stat. No signed product member uses this exception.
                    continue
                raise
            if not stat.S_ISREG(named.st_mode):
                raise ValueError(f"unsafe release filesystem entry: {rel}")
            if projection:
                owner = root.stat()
                if (named.st_nlink != 1 or named.st_mode & 0o7133
                        or (named.st_uid, named.st_gid) != (owner.st_uid, owner.st_gid)):
                    raise ValueError(f"unsafe generated runtime projection: {rel}")
                # The state can change at any time; it is not hashed or
                # included in a product mutation plan. Never rewrite it.
                continue
            digest = hashlib.sha256()
            fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, "rb") as stream:
                def identity(info):
                    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                            info.st_gid, info.st_nlink, info.st_size,
                            info.st_mtime_ns, info.st_ctime_ns)
                before = os.fstat(stream.fileno())
                if identity(named) != identity(before):
                    raise ValueError(f"release file replaced: {rel}")
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                if (identity(os.fstat(stream.fileno())) != identity(before)
                        or identity(entry.lstat()) != identity(before)):
                    raise ValueError(f"release file changed: {rel}")
            files[rel] = (stat.S_IMODE(before.st_mode), digest.hexdigest())
    return files


# Only the exact previously signed payload may explain installation drift.
# These are local data paths, not a general config/ or executable exemption.
_BASELINE_DIR = Path("/var/lib/capivara-dsm-928/installed-baseline")
_LOCAL_CONFIG = frozenset({
    "config/agent.conf", "config/agent.conf.template", "config/alerts.conf",
    "config/collectors.conf", "config/context.conf", "config/discord_config.sh",
    "config/events.conf", "config/metrics.config", "config/providers/steam.conf",
    "config/resources.json", "config/runtime.sh", "custom/providers/example-custom.sh",
    "config/catalog-resource-profiles/minecraft.json",
    "config/catalog-resource-profiles/palworld.json",
    "config/providers/curseforge-test-status.json", "config/providers/curseforge.key",
})
_LOCAL_DATA = frozenset({"dashboard/state/scheduler_state.json", "data/capivara.db",
                         "runtime/browser-sessions.json"})


def _reviewed_local_overlays(folder):
    """Root-owned explicit review of local configuration bytes/modes.

    Contains digests, never credentials or file contents. No self-enrollment
    from the installed tree. Changes require a new operator review.
    """
    path = folder / "local-overrides.json"
    if not path.exists() and not path.is_symlink():
        return {}
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_uid, info.st_mode,
                    info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_nlink != 1 or before.st_mode & 0o077
                or not 0 < before.st_size <= 32768
                or identity(path.lstat()) != identity(before)):
            raise ValueError("untrusted installed local override review")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(32769)
        if (len(raw) != before.st_size or identity(os.fstat(fd)) != identity(before)
                or identity(path.lstat()) != identity(before)):
            raise ValueError("local override review changed")
    finally:
        os.close(fd)
    value = json.loads(raw)
    if type(value) is not dict or set(value) - _LOCAL_CONFIG:
        raise ValueError("unsupported reviewed local override")
    result = {}
    for name, item in value.items():
        if (type(item) is not dict or set(item) != {"mode", "sha256"}
                or type(item["mode"]) is not int
                or not 0 <= item["mode"] <= 0o777 or item["mode"] & 0o002
                or type(item["sha256"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("invalid local override review")
        result[name] = (item["mode"], item["sha256"])
    return result


def _verified_cache(installed, name, actual, baseline, target):
    """Check cache bytes against a fresh compile of the authenticated source.

    Never deserialize untrusted marshal data. Only native CPython cache names
    and normal timestamp or checked-hash headers are accepted. A cache for
    a source being changed remains blocking until the transaction has an
    audited cache invalidation owner.
    """
    from importlib import _bootstrap_external as pyc
    cache = installed / name
    if cache.parent.name != "__pycache__" or sys.implementation.name != "cpython":
        return False
    match = re.fullmatch(r"(.+)\." + re.escape(sys.implementation.cache_tag)
                         + r"(?:\.opt-([12]))?\.pyc", cache.name)
    if not match:
        return False
    source = cache.parent.parent / (match.group(1) + ".py")
    relative = source.relative_to(installed).as_posix()
    if (relative not in baseline or actual.get(relative) != baseline[relative]
            or target.get(relative) != baseline[relative]):
        return False
    cs, ss = cache.lstat(), source.lstat()
    if (not stat.S_ISREG(cs.st_mode) or cs.st_nlink != 1
            or cs.st_mode & 0o7022 or cs.st_uid not in (0, ss.st_uid)
            or not 16 < cs.st_size <= 16 * 1024 * 1024
            or not 0 < ss.st_size <= 4 * 1024 * 1024):
        return False
    raw = cache.read_bytes()
    data = source.read_bytes()
    if (hashlib.sha256(raw).hexdigest() != actual[name][1]
            or hashlib.sha256(data).hexdigest() != baseline[relative][1]
            or raw[:4] != importlib.util.MAGIC_NUMBER):
        return False
    flags = struct.unpack("<I", raw[4:8])[0]
    try:
        code = compile(data, str(source), "exec", dont_inherit=True,
                       optimize=int(match.group(2) or 0))
        if flags == 0:
            stamp, size = struct.unpack("<II", raw[8:16])
            if size != len(data) & 0xffffffff:
                return False
            expected = pyc._code_to_timestamp_pyc(code, stamp, size)
        elif flags == 3:
            expected = pyc._code_to_hash_pyc(
                code, importlib.util.source_hash(data), checked=True)
        else:
            return False
    except (SyntaxError, ValueError, OverflowError, TypeError):
        return False
    return raw == expected


def _reconcile_signed_baseline(installed, actual, baseline, target, overrides):
    """Return a comparison view; never change installed or candidate files.

    A legitimate installed difference is normalized only when the old and
    new signed product entries are identical. An unexpected product drift
    must not become an eligible update even when it matches the new release.
    """
    if ("release-manifest.json" not in baseline or
            actual.get("release-manifest.json") != baseline["release-manifest.json"]):
        raise ValueError("installed manifest does not match signed baseline")
    adjusted = dict(target)
    counts = {"preserved_data": 0, "reviewed_local_configuration": 0,
              "installer_execute_mode": 0, "verified_unchanged_python_cache": 0}
    for name in sorted(actual.keys() | baseline.keys() | target.keys()):
        installed_value, old, new = actual.get(name), baseline.get(name), target.get(name)
        if installed_value == old:
            continue
        if old != new:
            raise ValueError("installed drift on changed release path: " + name)
        if installed_value is None:
            raise ValueError("installed signed baseline file missing: " + name)
        mode, digest = installed_value
        if name in _LOCAL_CONFIG and overrides.get(name) == installed_value:
            category = "reviewed_local_configuration"
        elif old is None and (name.startswith("backups/") or name in _LOCAL_DATA):
            category = "preserved_data"
        elif (old is not None and digest == old[1] and name.endswith(".sh")
              and old[0] == 0o644 and mode in (0o744, 0o745, 0o754, 0o755)):
            category = "installer_execute_mode"
        elif (old is None and _verified_cache(installed, name, actual, baseline, target)):
            category = "verified_unchanged_python_cache"
        else:
            raise ValueError("unreviewed installed baseline drift: " + name)
        adjusted[name] = installed_value
        counts[category] += 1
    return adjusted, counts


def _signed_baseline_comparison(installed, before, after):
    # An absent baseline preserves the legacy strict classifier (including
    # disposable fixtures). The fixed path is never provided by a request.
    if installed != Path("/opt/dsm") or not os.path.lexists(_BASELINE_DIR):
        return after, None
    loader = SourceFileLoader("dsm928_installed_baseline_review",
                              str(Path(__file__).with_name(
                                  "game-uptime-operational-release-review.py")))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    review = importlib.util.module_from_spec(spec)
    loader.exec_module(review)
    try:
        proof = review.verify_installed_baseline()
        if (proof.get("artifact_origin_verified") is not True
                or proof.get("target_tree_bound_to_signed_tar") is not True):
            raise ValueError("installed baseline not authenticated")
        baseline = _inventory(_BASELINE_DIR / "payload")
        overrides = _reviewed_local_overlays(_BASELINE_DIR)
        adjusted, counts = _reconcile_signed_baseline(
            installed, before, baseline, after, overrides)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise ValueError("installed baseline reconciliation blocked: " + str(exc)) from exc
    return adjusted, {"verified_archive_sha256": proof["verified_archive_sha256"],
                      "normalized_counts": counts}


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
    "dashboard/workers/hybrid_agent_worker.py",
    "dashboard/workers/hybrid_customer_workspace_worker.py",
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


def _control_plane_restart_plan(changed, before, after, fixed):
    """Exact diagnostic candidate, separate from executable file admission.

    Restrict the initial restart scope to existing dashboard Python files.
    Fence/bootstrap code and every other incompatible change remain blocked.
    Service ownership, import contracts and rollback still require proof.
    """
    candidates = []
    blockers = []
    for name in changed:
        if name in _BOOTSTRAP or "game_uptime" in name or "maintenance_hold" in name:
            blockers.append(name)
        elif (name.startswith("dashboard/") and name.endswith(".py")
              and "__pycache__" not in Path(name).parts
              and _change_tier(name, before, after) == "control_plane_restart_candidate"
              and before[name][0] == after[name][0]
              and not before[name][0] & 0o7133):
            candidates.append(name)
        elif not (name in before and name in after
                  and before[name][0] == after[name][0]
                  and not before[name][0] & 0o7133
                  and (name in ("version", "release-manifest.json")
                       or (name.startswith("dashboard/web/")
                           and Path(name).suffix.lower() in CONTROL_PLANE_SUFFIXES
                           and not name.endswith(".py")))):
            blockers.append(name)
    eligible = bool(candidates) and not blockers and not fixed["bootstrap_installation_required"]
    return {"status": "restart_candidate_review_only" if eligible else "blocked",
            "changed_paths": sorted(changed) if eligible else [],
            "candidate_python_file_count": len(candidates),
            "blocking_paths": blockers[:40],
            "blocking_path_count": len(blockers),
            "live_no_drain_authorized": False}


def analyze(installed: Path, target: Path) -> dict[str, object]:
    after = _inventory(target)
    signed_paths = None
    if installed == Path("/opt/dsm") and os.path.lexists(_BASELINE_DIR):
        # Do not omit a signed member even if it resembles generated state.
        # The reconciliation below independently authenticates the baseline.
        signed_paths = after.keys() | _inventory(_BASELINE_DIR / "payload").keys()
    before = _inventory(installed, signed_paths=signed_paths)
    after, baseline_review = _signed_baseline_comparison(installed, before, after)
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
        "installed_baseline_review": baseline_review,
        "fixed_file_transaction_plan": fixed,
        "control_plane_restart_plan": _control_plane_restart_plan(changed, before, after, fixed),
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
