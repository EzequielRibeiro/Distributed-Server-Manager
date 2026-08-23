#!/usr/bin/env python3
"""Phase 6 HTTP integration: safe customer instance creation boundary."""

from __future__ import annotations

from urllib.parse import urlparse

import server_part8 as integration
from instance_creation_http import (
    INSTANCE_CREATE_PATH,
    dispatch_instance_create_post,
)
from instance_creation_feedback import record_instance_creation_failure


legacy = integration.legacy
_previous_post = legacy.DashboardHandler.do_POST


def _contract_for_request(user, game: str) -> str | None:
    if not user or not game:
        return None
    try:
        contracts = legacy.customer_contracts(user)
    except Exception:
        return None

    for contract in contracts:
        if (
            str(contract.get("game_id", "")).strip().lower() == game
            and bool(contract.get("available"))
        ):
            value = str(contract.get("id", "")).strip()
            return value or None
    return None


def integrated_post(self):
    path = urlparse(self.path).path
    if path != INSTANCE_CREATE_PATH:
        return _previous_post(self)

    user = integration.integrated_authenticate(self.headers)
    if user is None:
        self.unauthorized()
        return

    try:
        payload = self.read_json_body()
    except ValueError:
        self.send_json(
            400,
            {
                "error": "invalid_request",
                "message": "Requisição inválida.",
            },
        )
        return

    result = dispatch_instance_create_post(
        path,
        payload,
        user=user,
        create_instance=legacy.create_customer_instance,
        contract_resolver=_contract_for_request,
        failure_reporter=lambda failure: record_instance_creation_failure(
            failure,
            root=legacy.DSM_ROOT,
            backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,
            notify=legacy.notify,
        ),
    )

    status, body = result
    self.send_json(status, body)


legacy.DashboardHandler.do_POST = integrated_post


def run():
    legacy.run()


if __name__ == "__main__":
    run()
