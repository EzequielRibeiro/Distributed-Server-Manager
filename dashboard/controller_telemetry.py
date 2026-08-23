#!/usr/bin/env python3
"""Controller-local telemetry built from the same Linux collector used by Agents."""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENT_RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(AGENT_RUNTIME) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNTIME))

from host_telemetry import collect_host_telemetry

_HISTORY: deque[dict[str, Any]] = deque(maxlen=720)
_LOCK = threading.Lock()


def _sample() -> dict[str, Any]:
    value = collect_host_telemetry()
    process = value.pop("agent", {})
    value["controller"] = process
    return value


def controller_telemetry(window_seconds: int = 3600) -> dict[str, Any]:
    """Return current Controller telemetry plus an in-process rolling history."""
    window = max(300, min(int(window_seconds or 3600), 86400))
    current = _sample()
    now = time.time()
    with _LOCK:
        _HISTORY.append(current)
        cutoff = now - window
        history = [item for item in _HISTORY if float(item.get("collected_at_unix") or 0) >= cutoff]
    return {
        "schema_version": 1,
        "kind": "ControllerTelemetry",
        "window_seconds": window,
        "current": current,
        "history": history,
    }


__all__ = ["controller_telemetry"]
