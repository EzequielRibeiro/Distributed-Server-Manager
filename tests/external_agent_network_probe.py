#!/usr/bin/env python3
"""Execute real Linux Agent network actions for the P4 external-network gate."""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import agent as linux_agent


def emit(value) -> None:
    print(json.dumps(value, sort_keys=True, default=str), flush=True)


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "resolve":
        hostname = sys.argv[2]
        started = time.perf_counter()
        address = socket.gethostbyname(hostname)
        emit({"hostname": hostname, "address": address, "dns_ms": round((time.perf_counter() - started) * 1000, 3)})
        return 0

    config = linux_agent._load_config()
    if action == "enroll":
        started = time.perf_counter()
        enrolled = linux_agent.enroll(config)
        emit({
            "agent_id": enrolled.get("agent_id"),
            "controller_id": enrolled.get("controller_id"),
            "credential_id": enrolled.get("credential_id"),
            "pairing_token_present": bool(enrolled.get("pairing_token")),
            "rtt_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        return 0

    if action == "heartbeat":
        started = time.perf_counter()
        result = linux_agent.heartbeat(config)
        emit({
            "agent_id": result.get("agent_id"),
            "health_status": result.get("health_status"),
            "status": result.get("status"),
            "doctor_state": result.get("doctor_state"),
            "doctor_command": bool(result.get("doctor_command")),
            "rtt_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        return 0

    raise SystemExit(f"unsupported action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
