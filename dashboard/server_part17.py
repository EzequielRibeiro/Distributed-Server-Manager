#!/usr/bin/env python3
"""Catalog architecture stages 5-10 composition layer."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse

import server_part16 as integration
from catalog_runtime_policy_http import RUNTIME_POLICY_PATH, dispatch_catalog_runtime_policy_get, dispatch_catalog_runtime_policy_put
from json_serialization import normalize_json_value

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_previous_put = getattr(legacy.DashboardHandler, "do_PUT", None)
_previous_send_json = legacy.DashboardHandler.send_json
_authenticate = integration._authenticate
_ROOT = Path(__file__).resolve().parents[1]


def json_safe_send_json(self, code, payload):
    """Serialize DB-native dates consistently across supported backends."""
    return _previous_send_json(self, code, normalize_json_value(payload))


def catalog_architecture_get(self):
    parsed = urlparse(self.path)
    if parsed.path != RUNTIME_POLICY_PATH:
        return _previous_get(self)
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized(); return
    status, body = dispatch_catalog_runtime_policy_get(parsed.path, parsed.query, user=user, root=_ROOT)
    self.send_json(status, body)


def catalog_architecture_put(self):
    parsed = urlparse(self.path)
    if parsed.path != RUNTIME_POLICY_PATH:
        if _previous_put is not None:
            return _previous_put(self)
        self.send_json(404, {"error": "not_found"}); return
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized(); return
    try:
        payload = self.read_json_body()
    except ValueError:
        self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."}); return
    status, body = dispatch_catalog_runtime_policy_put(parsed.path, payload, user=user, root=_ROOT)
    self.send_json(status, body)

legacy.DashboardHandler.send_json = json_safe_send_json
legacy.DashboardHandler.do_GET = catalog_architecture_get
legacy.DashboardHandler.do_PUT = catalog_architecture_put


def run():
    legacy.run()

if __name__ == "__main__":
    run()
