#!/usr/bin/env python3
"""Catalog game-data inventory composition layer."""
from __future__ import annotations

from urllib.parse import urlparse

import server_part15 as integration
from catalog_game_data_inventory_http import GAME_DATA_INVENTORY_PATH, dispatch_catalog_game_data_inventory_get

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_authenticate = integration._authenticate


def catalog_game_data_inventory_get(self):
    parsed = urlparse(self.path)
    if parsed.path != GAME_DATA_INVENTORY_PATH:
        return _previous_get(self)
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized()
        return
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


legacy.DashboardHandler.do_GET = catalog_game_data_inventory_get


def run():
    legacy.run()


if __name__ == "__main__":
    run()
