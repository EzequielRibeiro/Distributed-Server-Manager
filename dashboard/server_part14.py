#!/usr/bin/env python3
"""Dashboard v3 final composition layer.

Registers canonical UI routes without growing the legacy server.py module.
"""
from __future__ import annotations

import server_part13 as integration

legacy = integration.legacy

DASHBOARD_V3_FILES = {
    "/servers.html": legacy.WEB_DIR / "servers.html",
    "/servers.js": legacy.WEB_DIR / "servers.js",
    "/servers.css": legacy.WEB_DIR / "servers.css",
    "/agents.html": legacy.WEB_DIR / "agents.html",
    "/agents-v3.js": legacy.WEB_DIR / "agents-v3.js",
    "/agents-v3.css": legacy.WEB_DIR / "agents-v3.css",
    "/add-agent.html": legacy.WEB_DIR / "add-agent.html",
    "/add-agent-v3.css": legacy.WEB_DIR / "add-agent-v3.css",
    "/agent-details.html": legacy.WEB_DIR / "agent-details.html",
    "/agent-details.js": legacy.WEB_DIR / "agent-details.js",
    "/agent-details.css": legacy.WEB_DIR / "agent-details.css",
}

legacy.STATIC_FILES.update(DASHBOARD_V3_FILES)


def run():
    legacy.run()


if __name__ == "__main__":
    run()
