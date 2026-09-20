#!/usr/bin/env python3
"""Periodic compact snapshots for Database Intelligence growth analytics."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[2])).resolve()
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database_intelligence_repository import DatabaseIntelligenceRepository
from runtime_backend import backend_from_environment

INTERVAL_SECONDS = max(300, min(int(os.environ.get("DSM_DATABASE_INTELLIGENCE_SNAPSHOT_SECONDS", "3600")), 86400))
_ALLOWED_DB_KEYS = {
    "DSM_DATABASE_DRIVER","DSM_DATABASE","DSM_DATABASE_HOST","DSM_DATABASE_PORT",
    "DSM_DATABASE_NAME","DSM_DATABASE_USER","DSM_DATABASE_PASSWORD_FILE","DSM_DATABASE_TLS",
}


def _read_shell_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    pattern = re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            result[match.group(1)] = next((value for value in match.groups()[1:] if value is not None), "")
    return result


def _database_environment(root: Path = ROOT, environment: dict[str, str] | None = None) -> dict[str, str]:
    effective = dict(os.environ if environment is None else environment)
    for key, value in _read_shell_values(root / "config" / "dsm.conf").items():
        if key in _ALLOWED_DB_KEYS and key not in effective:
            effective[key] = value
    effective.setdefault("DSM_ROOT", str(root))
    return effective


def run_forever(root: Path = ROOT, interval: int = INTERVAL_SECONDS) -> None:
    backend = backend_from_environment(_database_environment(root))
    repo = DatabaseIntelligenceRepository(backend)
    repo.initialize()
    while True:
        try:
            result = repo.capture_snapshot()
            print(
                f"database intelligence snapshot day={result['snapshot_day']} "
                f"rows={result['rows']} size={result['database_size_bytes']}",
                flush=True,
            )
        except Exception as exc:
            print(f"database intelligence snapshot failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(max(300, int(interval)))


if __name__ == "__main__":
    run_forever()
