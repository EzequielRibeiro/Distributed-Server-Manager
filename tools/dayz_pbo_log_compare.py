#!/usr/bin/env python3
"""Read-only comparison of DayZ ENGINE PBO Load journal exports.

Input files are historical logs exported by an operator. This tool never
starts/stops DayZ, modifies owners, or treats a log difference as causal proof.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

LOAD = re.compile(r"ENGINE\s*:\s*PBO Load\s+['\"]([^'\"]+)['\"]")
DLC = frozenset({"nasdara", "sakhal"})
BASE = frozenset({"addons"})


def loaded_package_names(log: str) -> dict[str, set[str]]:
    """Return unique DLC package stems reported by the DayZ engine."""
    result: dict[str, set[str]] = {name: set() for name in DLC}
    for line in log.splitlines():
        match = LOAD.search(line)
        if not match:
            continue
        parts = match.group(1).replace("\\", "/").split("/")
        if "serverfiles" not in parts:
            continue
        remainder = parts[parts.index("serverfiles") + 1:]
        if len(remainder) == 3 and remainder[0] in DLC and remainder[1] == "addons":
            result[remainder[0]].add(remainder[2].lower())
    return result


def compare_installed(log: str, serverfiles: Path) -> dict[str, object]:
    """Compare engine-reported package stems with present PBO/EBO files (read-only)."""
    loaded = loaded_package_names(log)
    report: dict[str, object] = {}
    for dlc in sorted(DLC):
        addons = serverfiles / dlc / "addons"
        if addons.is_symlink() or not addons.is_dir():
            raise ValueError(f"missing_or_unsafe_dlc_addons:{dlc}")
        present: set[str] = set()
        for package in addons.iterdir():
            if package.is_symlink():
                raise ValueError(f"unsafe_dlc_addon_symlink:{dlc}")
            if package.is_file() and package.suffix.lower() in {".pbo", ".ebo"}:
                present.add(package.stem.lower())
        report[dlc] = {
            "files": len(present),
            "loaded_unique": len(loaded[dlc]),
            "missing_from_engine": sorted(present - loaded[dlc]),
            "unexpected_in_engine": sorted(loaded[dlc] - present),
        }
    return report


def inventory(log: str) -> dict[str, object]:
    counts: Counter[str] = Counter()
    packages: dict[str, set[str]] = {"nasdara": set(), "sakhal": set()}
    for line in log.splitlines():
        match = LOAD.search(line)
        if not match:
            continue
        # DayZ prints Windows separators after the addons directory on Linux.
        path = match.group(1).replace("\\", "/")
        parts = path.split("/")
        if "serverfiles" not in parts:
            continue
        remainder = parts[parts.index("serverfiles") + 1:]
        if not remainder:
            continue
        if remainder[0] in DLC and len(remainder) >= 3 and remainder[1] == "addons":
            dlc = remainder[0]
            counts[dlc] += 1
            packages[dlc].add("/".join(remainder[2:]).lower())
        elif remainder[0] == "addons" and len(remainder) >= 2:
            counts["base"] += 1
        else:
            counts["other"] += 1
    return {
        "base": counts["base"],
        "nasdara": counts["nasdara"],
        "sakhal": counts["sakhal"],
        "other": counts["other"],
        "total": sum(counts.values()),
        "unique_packages": {name: len(paths) for name, paths in packages.items()},
    }


def compare(before: str, after: str) -> dict[str, object]:
    a = inventory(before)
    b = inventory(after)
    return {
        "before": a,
        "after": b,
        "base_count_stable": a["base"] == b["base"],
        "dlc_delta": {dlc: b[dlc] - a[dlc] for dlc in sorted(DLC)},
        "causality_established": False,
        "note": "Log counts alone cannot prove that ownership was the sole changed variable.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="First exported DayZ journal")
    parser.add_argument("after", type=Path, help="Second exported DayZ journal")
    parser.add_argument("--serverfiles", type=Path, help="Optional read-only DLC file inventory")
    args = parser.parse_args()
    before = args.before.read_text(errors="replace")
    after = args.after.read_text(errors="replace")
    report = compare(before, after)
    if args.serverfiles is not None:
        report["installed_comparison"] = compare_installed(after, args.serverfiles)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
