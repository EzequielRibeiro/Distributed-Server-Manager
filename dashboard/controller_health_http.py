#!/usr/bin/env python3
"""Controller HTTP liveness endpoint.

`/health` is a liveness probe for the process that is serving the request.  It
must not infer Controller liveness from legacy worker state files.  Placement,
Agent reachability and other operational readiness belong to the
infrastructure doctor/readiness surfaces.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

HEALTH_PATH = "/health"


def controller_health_payload(legacy) -> dict:
    """Return liveness while retaining legacy state-file data as diagnostics."""
    legacy_states = {
        key: path.exists()
        for key, path in getattr(getattr(legacy, "STATE", None), "files", {}).items()
    }
    return {
        "schema_version": 2,
        "kind": "ControllerHealth",
        "score": 100,
        "status": "healthy",
        "states": {
            "dashboard": True,
            "controller": True,
        },
        "legacy_worker_state_files": legacy_states,
        "generated_at": int(time.time()),
    }


def install_controller_health_http(legacy) -> None:
    """Install the liveness route after legacy/integration route wrappers."""
    previous_get = legacy.DashboardHandler.do_GET

    def health_get(self):
        parsed = urlparse(self.path)
        if parsed.path == HEALTH_PATH:
            self.send_json(200, controller_health_payload(legacy))
            return
        return previous_get(self)

    legacy.DashboardHandler.do_GET = health_get
