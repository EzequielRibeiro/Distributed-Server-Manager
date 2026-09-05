#!/usr/bin/env python3
"""Canonical authentication-area policy for Dashboard static resources.

Static JavaScript/CSS cannot add ``X-Capivara-Auth-Area`` when loaded by a
browser ``<script>``/``<link>`` element. The final HTTP composition layer must
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
    "/dashboard-node-overview.css",
    "/dashboard-node-overview.js",
    "/components/sidebar-v3.html",
    "/sidebar-v3.js",
    "/activity-log.html",
    "/activity-log.js",
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
    "/agent-details-sidebar.js",
    "/agent-alert-link.js",
    "/agent-network-panel.js",
    "/agent-identity-rebind.js",
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
    "/catalog-v2.css",
    "/catalog-page.css",
    "/catalog-installation.css",
    "/catalog-page.js",
    "/catalog-game-create.html",
    "/catalog-game-create.css",
    "/catalog-game-create.js",
    "/game-profiles.html",
    "/game-profiles.css",
    "/game-profiles.js",
    "/game-profile-presentation.js",
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
    "/help.html",
    "/help.css",
    "/help.js",
})


CUSTOMER_STATIC_PATHS = frozenset({
    "/customer.html",
    "/contract-demo.html",
    "/customer-instance.html",
    "/customer-members.html",
    "/customer-account.html",
    "/customer-backups.html",
    "/customer-integrations.html",
    "/customer-change-password.html",
    "/customer.css",
    "/customer.js",
    "/customer-core.js",
    "/customer-navigation.js",
    "/customer-profile.js",
    "/customer-email-change.js",
    "/customer-placement-selector.js",
    "/customer-placement-client.js",
    "/runtime-selector.js",
    "/create-server-wizard.css",
    "/create-server-wizard.js",
    "/customer-instance.js",
    "/customer-instance-v2.css",
    "/customer-instance-v2.js",
    "/customer-instance-v2-wrapper.js",
    "/customer-instance-core.js",
    "/customer-instance-events.css",
    "/customer-instance-events.js",
    "/customer-instance-activity.js",
    "/customer-instance-connection.js",
    "/customer-instance-delete.js",
    "/customer-backup-transfer.js",
    "/customer-team.css",
    "/customer-members.js",
    "/customer-change-password.js",
    "/customer-account.js",
    "/customer-backups.js",
    "/customer-integrations.css",
    "/customer-integrations.js",
})


# Reusable browser code only. These resources carry no account data and are
# consumed by both portals. Their APIs remain independently authenticated.
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
