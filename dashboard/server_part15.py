#!/usr/bin/env python3
"""Catalog game-data architecture composition layer."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import server_part14 as integration
from catalog_game_data_inventory_http import GAME_DATA_INVENTORY_PATH, dispatch_catalog_game_data_inventory_get
from catalog_resource_profiles_http import (
    RESOURCE_PROFILES_PATH,
    dispatch_catalog_resource_profiles_delete,
    dispatch_catalog_resource_profiles_get,
    dispatch_catalog_resource_profiles_patch,
    dispatch_catalog_resource_profiles_post,
    dispatch_catalog_resource_profiles_put,
)

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_previous_post = legacy.DashboardHandler.do_POST
_previous_put = getattr(legacy.DashboardHandler, "do_PUT", None)
_previous_patch = getattr(legacy.DashboardHandler, "do_PATCH", None)
_previous_delete = getattr(legacy.DashboardHandler, "do_DELETE", None)
_controller_authenticate = integration.integration._controller_authenticate
_customer_authenticate = integration.integration._customer_authenticate
_ROOT = Path(__file__).resolve().parents[1]
legacy.STATIC_FILES["/game-profile-presentation.js"] = _ROOT / "dashboard" / "web" / "game-profile-presentation.js"


def _controller_user(self):
    user = _controller_authenticate(self.headers)
    if user is None:
        self.unauthorized()
    return user


def _resource_profiles_reader(self):
    """Authenticate the read-only profile catalog in the explicit browser area.

    Resource profiles are consumed by both the Controller catalog editor and the
    Customer server/profile selector. Mutating methods remain Controller-only.
    """
    area = str(self.headers.get("X-Capivara-Auth-Area") or "").strip().lower()
    if area == "customer":
        user = _customer_authenticate(self.headers)
    else:
        user = _controller_authenticate(self.headers)
    if user is None:
        self.unauthorized()
    return user


def _payload(self):
    try:
        return self.read_json_body()
    except Exception:
        self.send_json(400, {"error": "invalid_json"})
        return None


def catalog_architecture_get(self):
    parsed = urlparse(self.path)
    if parsed.path not in {RESOURCE_PROFILES_PATH, GAME_DATA_INVENTORY_PATH}:
        return _previous_get(self)
    if parsed.path == RESOURCE_PROFILES_PATH:
        user = _resource_profiles_reader(self)
        if user is None:
            return
        result = dispatch_catalog_resource_profiles_get(parsed.path, parsed.query, user=user, root=_ROOT)
    else:
        user = _controller_user(self)
        if user is None:
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


def catalog_architecture_post(self):
    parsed = urlparse(self.path)
    if parsed.path != RESOURCE_PROFILES_PATH:
        return _previous_post(self)
    user = _controller_user(self)
    if user is None:
        return
    payload = _payload(self)
    if payload is None:
        return
    status, body = dispatch_catalog_resource_profiles_post(parsed.path, payload, user=user, root=_ROOT)
    self.send_json(status, body)


def catalog_architecture_put(self):
    parsed = urlparse(self.path)
    if parsed.path != RESOURCE_PROFILES_PATH:
        if _previous_put is not None:
            return _previous_put(self)
        self.send_json(404, {"error": "not_found"})
        return
    user = _controller_user(self)
    if user is None:
        return
    payload = _payload(self)
    if payload is None:
        return
    status, body = dispatch_catalog_resource_profiles_put(parsed.path, payload, user=user, root=_ROOT)
    self.send_json(status, body)


def catalog_architecture_patch(self):
    parsed = urlparse(self.path)
    if parsed.path != RESOURCE_PROFILES_PATH:
        if _previous_patch is not None:
            return _previous_patch(self)
        self.send_json(404, {"error": "not_found"})
        return
    user = _controller_user(self)
    if user is None:
        return
    payload = _payload(self)
    if payload is None:
        return
    status, body = dispatch_catalog_resource_profiles_patch(parsed.path, payload, user=user, root=_ROOT)
    self.send_json(status, body)


def catalog_architecture_delete(self):
    parsed = urlparse(self.path)
    if parsed.path != RESOURCE_PROFILES_PATH:
        if _previous_delete is not None:
            return _previous_delete(self)
        self.send_json(404, {"error": "not_found"})
        return
    user = _controller_user(self)
    if user is None:
        return
    status, body = dispatch_catalog_resource_profiles_delete(parsed.path, parsed.query, user=user, root=_ROOT)
    self.send_json(status, body)


legacy.DashboardHandler.do_GET = catalog_architecture_get
legacy.DashboardHandler.do_POST = catalog_architecture_post
legacy.DashboardHandler.do_PUT = catalog_architecture_put
legacy.DashboardHandler.do_PATCH = catalog_architecture_patch
legacy.DashboardHandler.do_DELETE = catalog_architecture_delete


def run():
    legacy.run()


if __name__ == "__main__":
    run()
