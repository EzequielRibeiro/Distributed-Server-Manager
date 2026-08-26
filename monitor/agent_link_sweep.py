#!/usr/bin/env python3
"""Run one best-effort Controller Agent link health sweep."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("DSM_ROOT") or Path(__file__).resolve().parents[1])
DATABASE = ROOT / "database"
for item in (ROOT, DATABASE):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from agent_link_monitor import AgentLinkMonitor
from runtime_backend import backend_from_environment


def main() -> int:
    backend = backend_from_environment()
    try:
        result = AgentLinkMonitor(backend).sweep()
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
