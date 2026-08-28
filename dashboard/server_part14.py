#!/usr/bin/env python3
"""Dashboard v3 final composition layer.

Registers canonical UI routes without growing the legacy server.py module.
"""
from __future__ import annotations

import server_part13 as integration

legacy = integration.legacy

DASHBOARD_V3_FILES = {
    # Shared v3 shell.
    "/dashboard-v3.html": legacy.WEB_DIR / "dashboard-v3.html",
    "/dashboard-home-v3.css": legacy.WEB_DIR / "dashboard-home-v3.css",
    "/dashboard-home-v3.js": legacy.WEB_DIR / "dashboard-home-v3.js",
    "/components/sidebar-v3.html": legacy.WEB_DIR / "components" / "sidebar-v3.html",

    # Administration.
    "/customers.html": legacy.WEB_DIR / "customers.html",
    "/customers.js": legacy.WEB_DIR / "customers.js",
    "/users.html": legacy.WEB_DIR / "users.html",
    "/users.js": legacy.WEB_DIR / "users.js",
    "/system.html": legacy.WEB_DIR / "system.html",
    "/system.css": legacy.WEB_DIR / "system.css",
    "/system.js": legacy.WEB_DIR / "system.js",

    # Infrastructure.
    "/infrastructure.html": legacy.WEB_DIR / "infrastructure.html",
    "/infrastructure-v3.css": legacy.WEB_DIR / "infrastructure-v3.css",
    "/infrastructure-v3.js": legacy.WEB_DIR / "infrastructure-v3.js",
    "/agents.html": legacy.WEB_DIR / "agents.html",
    "/agents-v3.js": legacy.WEB_DIR / "agents-v3.js",
    "/agents-v3.css": legacy.WEB_DIR / "agents-v3.css",
    "/agent-steam-status.css": legacy.WEB_DIR / "agent-steam-status.css",
    "/agent-updates-v3.css": legacy.WEB_DIR / "agent-updates-v3.css",
    "/agent-updates-v3.js": legacy.WEB_DIR / "agent-updates-v3.js",
    "/add-agent.html": legacy.WEB_DIR / "add-agent.html",
    "/add-agent-linux.html": legacy.WEB_DIR / "add-agent-linux.html",
    "/add-agent-windows.html": legacy.WEB_DIR / "add-agent-windows.html",
    "/add-agent-v3.css": legacy.WEB_DIR / "add-agent-v3.css",
    "/add-agent-page.js": legacy.WEB_DIR / "add-agent-page.js",
    "/agent-installation.js": legacy.WEB_DIR / "agent-installation.js",
    "/agent-installation-wizard.js": legacy.WEB_DIR / "agent-installation-wizard.js",
    "/agent-details.html": legacy.WEB_DIR / "agent-details.html",
    "/agent-details.js": legacy.WEB_DIR / "agent-details.js",
    "/agent-details.css": legacy.WEB_DIR / "agent-details.css",
    "/agent-storage-pools.js": legacy.WEB_DIR / "agent-storage-pools.js",
    "/agent-storage-pools.css": legacy.WEB_DIR / "agent-storage-pools.css",
    "/storage-pool-source-cleanup.js": legacy.WEB_DIR / "storage-pool-source-cleanup.js",
    "/agent-observability.html": legacy.WEB_DIR / "agent-observability.html",
    "/agent-observability.css": legacy.WEB_DIR / "agent-observability.css",
    "/agent-observability.js": legacy.WEB_DIR / "agent-observability.js",
    "/agent-queue-details-state.js": legacy.WEB_DIR / "agent-queue-details-state.js",

    # Servers and catalog.
    "/servers.html": legacy.WEB_DIR / "servers.html",
    "/servers.js": legacy.WEB_DIR / "servers.js",
    "/servers.css": legacy.WEB_DIR / "servers.css",
    "/catalog.html": legacy.WEB_DIR / "catalog.html",
    "/catalog-page.css": legacy.WEB_DIR / "catalog-page.css",
    "/catalog-installation.css": legacy.WEB_DIR / "catalog-installation.css",
    "/catalog-page.js": legacy.WEB_DIR / "catalog-page.js",
    "/game-profiles.html": legacy.WEB_DIR / "game-profiles.html",
    "/game-profiles.css": legacy.WEB_DIR / "game-profiles.css",
    "/game-profiles.js": legacy.WEB_DIR / "game-profiles.js",

    # Operations and observability.
    "/operations.html": legacy.WEB_DIR / "operations.html",
    "/operations.css": legacy.WEB_DIR / "operations.css",
    "/operations.js": legacy.WEB_DIR / "operations.js",
    "/observability.html": legacy.WEB_DIR / "observability.html",
    "/observability.css": legacy.WEB_DIR / "observability.css",
    "/observability.js": legacy.WEB_DIR / "observability.js",
}

legacy.STATIC_FILES.update(DASHBOARD_V3_FILES)


def run():
    legacy.run()


if __name__ == "__main__":
    run()
