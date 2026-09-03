"""Generic runtime readiness/health policy for Capivara DSM P1."""
from __future__ import annotations
from typing import Any, Mapping

READINESS_VERSION = 1
VALID_STATES = {"ready", "degraded", "unready", "unknown"}


def evaluate_runtime_readiness(signals: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(signals, Mapping):
        raise ValueError("signals must be an object")
    required = {"process", "network"}
    missing = sorted(required - set(signals))
    if missing:
        state = "unknown"
        reasons = [f"missing:{name}" for name in missing]
    else:
        process = bool(signals.get("process"))
        network = bool(signals.get("network"))
        query = signals.get("query")
        if not process:
            state, reasons = "unready", ["process"]
        elif not network:
            state, reasons = "unready", ["network"]
        elif query is False:
            state, reasons = "degraded", ["query"]
        else:
            state, reasons = "ready", []
    return {"readiness_version": READINESS_VERSION, "kind": "RuntimeReadiness", "state": state, "ready": state == "ready", "reasons": reasons, "signals": dict(signals)}
