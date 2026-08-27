#!/usr/bin/env python3
"""HTTP composition for Customer geographic placement discovery."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from alert_repository import AlertSession
from customer_health_service import CustomerHealthService
from customer_placement_locations import customer_placement_locations
from customer_reference import resolve_customer_reference

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


def _record_placement_failure(backend, user, query) -> None:
    if not user or str(user.get("role") or "").lower() != "customer" or not user.get("scope_id"):
        return
    try:
        customer_id = resolve_customer_reference(user["scope_id"], public_only=isinstance(user["scope_id"], str))
        ph = "?" if backend.name == "sqlite" else "%s"
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                row = session.execute(f"SELECT id,controller_id FROM customers WHERE id={ph}", (customer_id,)).fetchone()
            finally:
                session.close()
        if row is None:
            return
        contract_id = str((query.get("contract") or [""])[0]).strip() or None
        game = str((query.get("game") or [""])[0]).strip().lower() or None
        dedupe_key = f"placement-locations:{row['id']}:{contract_id or game or 'general'}"
        CustomerHealthService(backend).failure(
            customer_id=str(row["id"]),
            controller_id=str(row["controller_id"]),
            dedupe_key=dedupe_key,
            event_type="CUSTOMER_PLACEMENT_FAILED",
            severity="ERROR",
            safe_code="placement_locations_unavailable",
            message="Não foi possível consultar uma localização disponível para o cliente.",
            actor_id=str(user.get("username") or "") or None,
            actor_role="customer",
            action="customer.placement.locations",
            contract_id=contract_id,
        )
    except Exception:
        pass


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
        query = parse_qs(parsed.query)
        backend = _backend(legacy)
        status, payload = dispatch_customer_placement_locations_get(parsed.path, user=user, backend=backend, query=query)
        if status >= 500:
            _record_placement_failure(backend, user, query)
        self.send_json(status, payload)
    legacy.DashboardHandler.do_GET = do_get


__all__ = ["CUSTOMER_PLACEMENT_LOCATIONS_PATH", "dispatch_customer_placement_locations_get", "install_customer_placement_locations"]
