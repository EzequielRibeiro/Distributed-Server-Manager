#!/usr/bin/env python3
"""Catalog secure game-data file manager composition layer."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse

import server_part15 as integration
from agent_game_data_http import GAME_DATA_FILES_PATH, dispatch_agent_game_data_post

legacy = integration.legacy
_previous_post = legacy.DashboardHandler.do_POST
_controller_authenticate = integration._controller_authenticate
_customer_authenticate = integration._customer_authenticate
_authenticate = _controller_authenticate
_ROOT = Path(__file__).resolve().parents[1]


def catalog_file_manager_post(self):
    parsed = urlparse(self.path)
    if parsed.path != GAME_DATA_FILES_PATH:
        return _previous_post(self)
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized(); return
    try:
        payload = self.read_json_body()
    except ValueError:
        self.send_json(400, {"error":"invalid_request","message":"Requisição inválida."}); return
    result = dispatch_agent_game_data_post(parsed.path, payload, user=user, backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend, root=_ROOT)
    if result is None:
        return _previous_post(self)
    status, body = result
    self.send_json(status, body)


legacy.DashboardHandler.do_POST = catalog_file_manager_post


def run(): legacy.run()

if __name__ == "__main__": run()
