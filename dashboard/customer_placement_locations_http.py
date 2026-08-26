#!/usr/bin/env python3
"""HTTP composition for Customer geographic placement discovery."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from customer_placement_locations import customer_placement_locations

CUSTOMER_PLACEMENT_LOCATIONS_PATH = "/api/customer/placement/locations"


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _float_arg(query: dict[str, list[str]], name: str):
    raw = str((query.get(name) or [""])[0]).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(name + " must be numeric")


def dispatch_customer_placement_locations_get(path: str, *, user, backend, query=None):
    if path != CUSTOMER_PLACEMENT_LOCATIONS_PATH:
        return None
    query = query or {}
    try:
        payload = customer_placement_locations(
            user,
            backend,
            game_id=str((query.get("game") or [""])[0]).strip() or None,
            runtime_id=str((query.get("runtime") or [""])[0]).strip() or None,
            contract_id=str((query.get("contract") or [""])[0]).strip() or None,
            client_latitude=_float_arg(query, "latitude"),
            client_longitude=_float_arg(query, "longitude"),
        )
        return 200, payload
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso não autorizado."}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "placement_locations_unavailable", "message": "Não foi possível consultar as localizações disponíveis."}


def install_customer_placement_locations(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path != CUSTOMER_PLACEMENT_LOCATIONS_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        status, payload = dispatch_customer_placement_locations_get(parsed.path, user=user, backend=_backend(legacy), query=parse_qs(parsed.query))
        self.send_json(status, payload)
    legacy.DashboardHandler.do_GET = do_get


__all__ = ["CUSTOMER_PLACEMENT_LOCATIONS_PATH", "dispatch_customer_placement_locations_get", "install_customer_placement_locations"]
