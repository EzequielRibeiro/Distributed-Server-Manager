#!/usr/bin/env python3
"""Agent-owned game-data orchestration integration layer."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import server_part13 as integration
from agent_game_data_api import game_data_job_status, queue_game_data_install

legacy = integration.legacy
_previous_get = legacy.DashboardHandler.do_GET
_previous_post = legacy.DashboardHandler.do_POST
_authenticate = integration._authenticate
ROOT_DIR = Path(__file__).resolve().parents[1]
GAME_DATA_STATUS_PATH = "/api/agents/game-data/jobs"
ENVIRONMENT_INSTALL_PATH = "/api/catalog/environment-install"


def _user(self):
    user = _authenticate(self.headers)
    if user is None:
        self.unauthorized()
    return user


def _backend():
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def integrated_get(self):
    parsed = urlparse(self.path)
    if parsed.path != GAME_DATA_STATUS_PATH:
        return _previous_get(self)
    user = _user(self)
    if user is None:
        return
    query = parse_qs(parsed.query)
    try:
        result = game_data_job_status(
            user,
            backend=_backend(),
            job_id=(query.get("job_id") or [None])[0],
            agent_id=(query.get("agent_id") or [None])[0],
        )
    except PermissionError:
        self.forbidden()
        return
    except KeyError:
        self.send_json(404, {"error": "game_data_job_not_found", "message": "Operação de game-data não encontrada."})
        return
    except ValueError as exc:
        self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        return
    self.send_json(200, result)


def integrated_post(self):
    parsed = urlparse(self.path)
    if parsed.path != ENVIRONMENT_INSTALL_PATH:
        return _previous_post(self)
    user = _user(self)
    if user is None:
        return
    try:
        payload = self.read_json_body()
        result = queue_game_data_install(
            user,
            payload,
            backend=_backend(),
            root=ROOT_DIR,
        )
    except PermissionError:
        self.forbidden()
        return
    except ValueError as exc:
        self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        return
    except RuntimeError as exc:
        self.send_json(409, {"error": "game_data_prepare_failed", "message": str(exc)})
        return
    self.send_json(202, result)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
