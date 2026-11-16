#!/usr/bin/env python3
"""Read-only, fail-closed audit of DayZ DLC package discovery preconditions.

A readable PBO is not necessarily discovered by the DayZ engine. In a DayZ 1.30
incident, DLC package directories owned by a different UID from the instance
runner were skipped even though the runner had POSIX read access. This audit
records that discrepancy; it deliberately does NOT change permissions or claim
that matching ownership guarantees a successful engine load.
"""
from __future__ import annotations

import pwd
import stat
from pathlib import Path
from typing import Any

MAX_DLC_ROOTS = 32
MAX_ADDON_ENTRIES = 4096
MAX_TOP_LEVEL_ENTRIES = 2048
KNOWN_DAYZ_DLC_ROOTS = frozenset({"nasdara", "sakhal"})
# The base-game package and mod directories are not optional DLC roots.
EXCLUDED = frozenset({
    "addons", "dta", "keys", "battleye", "mpmissions", "mods",
    "profiles", "steamapps", "logs", "config", "cfg", "bin",
})


def audit_dayz_dlc_roots(
    root: Path, *, runtime_user: str = "capivara-instance", expected_uid: int | None = None
) -> dict[str, Any]:
    """Describe DLC roots, never follow symlinks or write to the installation."""
    root = Path(root)
    try:
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or root.is_symlink():
            return {"status": "unsafe", "reason": "invalid_install_root", "roots": []}
        if expected_uid is None:
            expected_uid = pwd.getpwnam(runtime_user).pw_uid
    except (OSError, KeyError, ValueError):
        return {"status": "unknown", "reason": "root_or_runtime_user_unavailable", "roots": []}

    findings: list[dict[str, Any]] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return {"status": "unknown", "reason": "cannot_list_install_root", "roots": []}
    if len(children) > MAX_TOP_LEVEL_ENTRIES:
        return {"status": "unknown", "reason": "install_root_entry_limit", "roots": []}
    for path in children:
        name = path.name.lower()
        if name in EXCLUDED or name.startswith((".", "@")):
            continue
        try:
            entry = path.lstat()
            if stat.S_ISLNK(entry.st_mode):
                if name in KNOWN_DAYZ_DLC_ROOTS:
                    return {"status": "unsafe", "reason": "dlc_root_symlink", "roots": findings}
                # Unrelated top-level links are not evidence of DLC packages.
                continue
            if not stat.S_ISDIR(entry.st_mode):
                continue
            addons = path / "addons"
            try:
                addon_stat = addons.lstat()
            except FileNotFoundError:
                # Many legitimate game-data directories have no addons folder.
                # A missing one within a known DLC is instead incomplete.
                if name in KNOWN_DAYZ_DLC_ROOTS:
                    return {"status": "unknown", "reason": "known_dlc_missing_addons", "roots": findings}
                continue
            if not stat.S_ISDIR(addon_stat.st_mode):
                return {"status": "unsafe", "reason": "unsafe_dlc_addons", "roots": findings}
            # Check only immediate addon entries and keep work bounded.
            packages = 0
            mismatched_files = 0
            addon_entries = 0
            for item in addons.iterdir():
                addon_entries += 1
                if addon_entries > MAX_ADDON_ENTRIES:
                    return {"status": "unknown", "reason": "dlc_addon_entry_limit", "roots": findings}
                item_stat = item.lstat()
                if stat.S_ISLNK(item_stat.st_mode):
                    return {"status": "unsafe", "reason": "dlc_addon_symlink", "roots": findings}
                if stat.S_ISREG(item_stat.st_mode) and item.suffix.lower() in (".pbo", ".ebo"):
                    packages += 1
                    if item_stat.st_uid != expected_uid:
                        mismatched_files += 1
            if not packages:
                # A known DLC directory left behind by an interrupted update
                # is not healthy merely because it contains no PBOs.
                if name in KNOWN_DAYZ_DLC_ROOTS:
                    return {"status": "unknown", "reason": "known_dlc_no_packages", "roots": findings}
                continue
            if len(findings) >= MAX_DLC_ROOTS:
                return {"status": "unknown", "reason": "dlc_root_limit", "roots": findings}
            findings.append({
                "directory": path.name,
                "packages": packages,
                "package_owner_mismatch_count": mismatched_files,
                "owner_uid": entry.st_uid,
                "owner_gid": entry.st_gid,
                "owner_mode": oct(stat.S_IMODE(entry.st_mode)),
                "addons_owner_uid": addon_stat.st_uid,
                "addons_mode": oct(stat.S_IMODE(addon_stat.st_mode)),
                "expected_uid": expected_uid,
                "owner_matches_runner": entry.st_uid == expected_uid,
                "addons_owner_matches_runner": addon_stat.st_uid == expected_uid,
            })
        except FileNotFoundError:
            # A concurrent Steam update can remove a directory while audited.
            continue
        except OSError:
            return {"status": "unknown", "reason": "cannot_inspect_dlc", "roots": findings}

    mismatch = any(
        not r["owner_matches_runner"]
        or not r["addons_owner_matches_runner"]
        or r["package_owner_mismatch_count"] > 0
        for r in findings
    )
    return {
        "status": "warning" if mismatch else "ok",
        "reason": "dlc_owner_mismatch_may_skip_packages" if mismatch else None,
        "roots": findings,
        "runtime_user": runtime_user,
        "expected_uid": expected_uid,
        "read_only": True,
    }



def audit_dayz_manifest_provenance(
    root: Path, steam_home: Path, agent_state: Path, *,
    runtime_user: str = "capivara-instance", expected_uid: int | None = None,
) -> dict[str, Any]:
    """Read-only comparison of installed PBO metadata against Steam depot manifests.

    A positive ownership check is never proof of engine loading. No filesystem
    permissions are changed, and unverified files are not repair candidates.
    """
    structural = audit_dayz_dlc_roots(
        root, runtime_user=runtime_user, expected_uid=expected_uid
    )
    result: dict[str, Any] = {
        "kind": "DayZManifestProvenanceAudit",
        "read_only": True,
        "engine_load_verified": False,
        "status": "unverified",
        "reason": None,
        "verified_package_count": 0,
        "unverified_package_count": 0,
        "roots": [],
    }
    if structural["status"] not in {"ok", "warning"}:
        result.update(status=structural["status"], reason=structural.get("reason"))
        return result
    try:
        from .dayz_dlc_ownership import verified_dayz_dlc_paths_from_steam_home
    except ImportError:
        from dayz_dlc_ownership import verified_dayz_dlc_paths_from_steam_home
    try:
        verified = verified_dayz_dlc_paths_from_steam_home(
            Path(root), Path(steam_home), Path(agent_state)
        )
    except (ValueError, OSError):
        result.update(status="unsafe", reason="steam_manifest_untrusted_or_unavailable")
        return result

    verified_by_root: dict[str, set[str]] = {}
    for path in verified:
        path = Path(path)
        if path.suffix.lower() not in {".pbo", ".ebo"}:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            result.update(status="unsafe", reason="manifest_path_outside_root")
            return result
        if len(relative.parts) != 3 or relative.parts[1].lower() != "addons":
            continue
        verified_by_root.setdefault(relative.parts[0], set()).add(relative.parts[2])

    if not verified_by_root:
        result["reason"] = "no_installed_steam_manifest_proof"
        return result

    for finding in structural["roots"]:
        name = finding["directory"]
        official = verified_by_root.get(name, set())
        if not official:
            # A custom addon directory is not official DLC merely because it
            # has the same structure. Never propose ownership changes to it.
            continue
        addon_root = Path(root) / name / "addons"
        try:
            observed = {
                path.name for path in addon_root.iterdir()
                if path.suffix.lower() in {".pbo", ".ebo"} and path.is_file()
                and not path.is_symlink()
            }
        except OSError:
            result.update(status="unknown", reason="cannot_inspect_verified_dlc")
            return result
        result["verified_package_count"] += len(official & observed)
        result["unverified_package_count"] += len(observed - official)
        result["roots"].append({
            "directory": name,
            "verified_packages": len(official & observed),
            "unverified_packages": len(observed - official),
            "owner_mismatch_count": finding["package_owner_mismatch_count"],
            "owner_matches_runner": finding["owner_matches_runner"],
            "addons_owner_matches_runner": finding["addons_owner_matches_runner"],
        })
    if not result["roots"]:
        result["reason"] = "manifest_evidence_does_not_match_installed_dlc"
        return result
    has_mismatch = any(
        not r["owner_matches_runner"] or not r["addons_owner_matches_runner"]
        or r["owner_mismatch_count"] or r["unverified_packages"]
        for r in result["roots"]
    )
    result["status"] = "warning" if has_mismatch else "ok"
    result["reason"] = "ownership_or_provenance_review_required" if has_mismatch else None
    return result


__all__ = [
    "KNOWN_DAYZ_DLC_ROOTS", "MAX_ADDON_ENTRIES", "MAX_DLC_ROOTS",
    "MAX_TOP_LEVEL_ENTRIES", "audit_dayz_dlc_roots", "audit_dayz_manifest_provenance",
]
