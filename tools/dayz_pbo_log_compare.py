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
    args = parser.parse_args()
    print(json.dumps(compare(args.before.read_text(errors="replace"),
                             args.after.read_text(errors="replace")), indent=2))


if __name__ == "__main__":
    main()
