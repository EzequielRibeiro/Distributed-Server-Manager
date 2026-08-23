#!/usr/bin/env python3
"""Catalog game-data architecture composition layer."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import server_part14 as integration
from catalog_game_data_inventory_http import GAME_DATA_INVENTORY_PATH, dispatch_catalog_game_data_inventory_get
from catalog_resource_profiles_http import RESOURCE_PROFILES_PATH, dispatch_catalog_resource_profiles_get

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_authenticate = integration.integration._authenticate
_ROOT = Path(__file__).resolve().parents[1]


def catalog_architecture_get(self):
    parsed = urlparse(self.path)
    if parsed.path not in {RESOURCE_PROFILES_PATH, GAME_DATA_INVENTORY_PATH}:
        return _previous_get(self)
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized()
        return
    if parsed.path == RESOURCE_PROFILES_PATH:
        result = dispatch_catalog_resource_profiles_get(parsed.path, parsed.query, user=user, root=_ROOT)
    else:
        result = dispatch_catalog_game_data_inventory_get(
            parsed.path,
            parsed.query,
            user=user,
            backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
        )
    if result is None:
        return _previous_get(self)
    status, body = result
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = catalog_architecture_get


def run():
    legacy.run()


if __name__ == "__main__":
    run()
