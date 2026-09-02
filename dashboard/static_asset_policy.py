#!/usr/bin/env python3
"""Canonical authentication-area policy for Dashboard static resources.

Static JavaScript/CSS cannot add ``X-Capivara-Auth-Area`` when loaded by a
browser ``<script>``/``<link>`` element.  The final HTTP composition layer must
therefore know the intended portal area from the resource path itself instead
of falling back to ambiguous legacy authentication.
"""
from __future__ import annotations


CONTROLLER_STATIC_PATHS = frozenset({
    "/",
    "/index.html",
    "/controller-dashboard.js",
    "/controller-dashboard.css",
    "/dashboard-v3.html",
    "/dashboard-home-v3.css",
    "/dashboard-home-v3.js",
    "/components/sidebar-v3.html",
    "/customers.html",
    "/customers.js",
    "/customer-create.html",
    "/customer-create.js",
    "/customer-admin.html",
    "/customer-admin.js",
    "/customer-admin.css",
    "/customer-contract-create.html",
    "/customer-contract-create.js",
    "/customer-management-shell.js",
    "/customer-management.css",
    "/users.html",
    "/users.js",
    "/system.html",
    "/system.css",
    "/system.js",
    "/system-change-password.html",
    "/system-change-password.js",
    "/infrastructure.html",
    "/regions.html",
    "/datacenters.html",
    "/placement.html",
    "/infrastructure-v3.css",
    "/infrastructure-v3.js",
    "/infrastructure-role-ui.js",
    "/agents.html",
    "/agents-v3.js",
    "/agents-v3.css",
    "/agent-steam-status.css",
    "/agent-updates.js",
    "/agent-updates-v3.css",
    "/agent-updates-v3.js",
    "/agent-terminal.css",
    "/add-agent.html",
    "/add-agent-linux.html",
    "/add-agent-windows.html",
    "/add-agent-v3.css",
    "/add-agent-page.js",
    "/agent-installation.js",
    "/agent-installation-wizard.js",
    "/agent-location-ui.js",
    "/agent-details.html",
    "/agent-details.js",
    "/agent-details.css",
    "/agent-alert-link.js",
    "/agent-uninstall-admin.js",
    "/agent-storage-pools.js",
    "/agent-storage-pools.css",
    "/storage-pool-source-cleanup.js",
    "/agent-observability.html",
    "/agent-observability.css",
    "/agent-observability.js",
    "/agent-queue-details-state.js",
    "/game-data-orchestration.js",
    "/servers.html",
    "/servers.js",
    "/servers.css",
    "/catalog.html",
    "/catalog-page.css",
    "/catalog-installation.css",
    "/catalog-page.js",
    "/game-profiles.html",
    "/game-profiles.css",
    "/game-profiles.js",
    "/operations.html",
    "/operations.css",
    "/operations.js",
    "/observability.html",
    "/alerts.html",
    "/alerts-page-enhancements.js",
    "/events.html",
    "/monitoring.html",
    "/controller-logs.html",
    "/diagnostics.html",
    "/observability.css",
    "/observability.js",
})


CUSTOMER_STATIC_PATHS = frozenset({
    "/create-server-wizard.js",
    "/create-server-wizard.css",
    "/customer-instance-events.js",
    "/customer-instance-events.css",
    "/customer-change-password.html",
    "/customer-change-password.js",
    "/customer-members.html",
    "/customer-members.js",
    "/customer-team.css",
    "/customer-placement-selector.js",
    "/customer-profile.js",
    "/customer-email-change.js",
    "/customer-navigation.js",
    "/customer.js",
    "/customer-core.js",
    "/customer-integrations.html",
    "/customer-integrations.js",
    "/customer-integrations.css",
    "/customer-backups.html",
    "/customer-backups.js",
    "/customer-account.html",
    "/customer-account.js",
})


# These files contain reusable browser code only.  They carry no account data
# and are consumed by both portals, so making their transport area-neutral
# avoids forcing either Controller or Customer authentication onto the other.
SHARED_PUBLIC_STATIC_PATHS = frozenset({
    "/browser-auth-client.js",
    "/telemetry-widgets.css",
    "/telemetry-widgets.js",
})


def validate_static_asset_policy() -> None:
    groups = {
        "controller": CONTROLLER_STATIC_PATHS,
        "customer": CUSTOMER_STATIC_PATHS,
        "shared": SHARED_PUBLIC_STATIC_PATHS,
    }
    names = tuple(groups)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1:]:
            overlap = groups[left_name] & groups[right_name]
            if overlap:
                raise RuntimeError(
                    f"static asset policy overlap {left_name}/{right_name}: "
                    + ", ".join(sorted(overlap))
                )


validate_static_asset_policy()


__all__ = [
    "CONTROLLER_STATIC_PATHS",
    "CUSTOMER_STATIC_PATHS",
    "SHARED_PUBLIC_STATIC_PATHS",
    "validate_static_asset_policy",
]
