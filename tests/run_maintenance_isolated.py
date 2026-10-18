#!/usr/bin/env python3
"""Run maintenance test modules separately to isolate platform-specific imports."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def main() -> int:
    files = sorted(set(TESTS.glob("*maintenance*test.py")) | set(TESTS.glob("maintenance*test.py")))
    if not files:
        print("No maintenance tests found", file=sys.stderr)
        return 1
    failed = []
    for path in files:
        print(f"\n=== {path.name} ===", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(TESTS), "-p", path.name, "-v"],
            cwd=ROOT,
            check=False,
        )
        if result.returncode:
            failed.append(path.name)
    print(f"\nMaintenance modules: {len(files)}, failed: {len(failed)}")
    for name in failed:
        print(f"FAILED: {name}", file=sys.stderr)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
