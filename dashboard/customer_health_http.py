#!/usr/bin/env python3
"""HTTP surface for Customer functional health and administrative problem summaries."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from activity_audit_repository import ActivityAuditRepository
from alert_repository import AlertSession
from customer_health_repository import CustomerHealthRepository
from customer_reference import resolve_customer_reference

ADMIN_API = "/api/admin/customer-health"
ADMIN_ACTION_API = "/api/admin/customer-health/action"
CUSTOMER_API = "/api/customer/health"


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _customer_context(backend, reference):
    customer_id = resolve_customer_reference(reference, public_only=isinstance(reference, str))
    ph = "?" if backend.name == "sqlite" else "%s"
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                f"SELECT id,controller_id FROM customers WHERE id={ph}", (customer_id,)
            ).fetchone()
        finally:
            session.close()
    if row is None:
        raise PermissionError("Customer scope not found")
    return str(row["id"]), str(row["controller_id"])


def _health(rows):
    if any(str(item.get("level") or "").upper() == "CRITICAL" for item in rows):
        return "critical"
    if rows:
        return "degraded"
    return "healthy"


def install_customer_health_http(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def identity(headers):
        return authenticate(headers)

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {ADMIN_API, CUSTOMER_API}:
            return previous_get(self)
        user = identity(self.headers)
        if user is None:
            self.unauthorized(); return
        backend = _backend(legacy)
        repo = CustomerHealthRepository(backend)
        query = parse_qs(parsed.query or "")
        active = str((query.get("active") or ["true"])[0]).lower() not in {"0", "false", "no"}
        try:
            limit = max(1, min(int((query.get("limit") or ["200"])[0]), 1000))
        except ValueError:
            limit = 200

        role = str(user.get("role") or "").lower()
        if parsed.path == CUSTOMER_API:
            if role != "customer" or not user.get("scope_id"):
                self.send_json(403, {"error": "forbidden"}); return
            try:
                customer_id, _controller_id = _customer_context(backend, user["scope_id"])
            except PermissionError:
                self.send_json(403, {"error": "forbidden"}); return
            incidents = repo.list_incidents(customer_id=customer_id, active_only=active, limit=limit)
            self.send_json(200, {"health": _health(incidents), "count": len(incidents), "incidents": incidents})
            return

        if role not in {"admin", "controller"}:
            self.send_json(403, {"error": "forbidden"}); return
        controller_id = str(user.get("scope_id") or "").strip() if role == "controller" else None
        requested_customer = str((query.get("customer_id") or [""])[0]).strip() or None
        if requested_customer:
            try:
                customer_id, customer_controller = _customer_context(backend, requested_customer)
            except (PermissionError, ValueError):
                self.send_json(404, {"error": "customer_not_found"}); return
            if controller_id and customer_controller != controller_id:
                self.send_json(403, {"error": "forbidden"}); return
        else:
            customer_id = None
        incidents = repo.list_incidents(
            customer_id=customer_id,
            controller_id=controller_id,
            active_only=active,
            limit=limit,
        )
        customers = len({str(item.get("customer_id")) for item in incidents})
        self.send_json(200, {
            "health": _health(incidents),
            "count": len(incidents),
            "customers_with_problems": customers,
            "incidents": incidents,
        })

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path != ADMIN_ACTION_API:
            return previous_post(self)
        user = identity(self.headers)
        if user is None:
            self.unauthorized(); return
        role = str(user.get("role") or "").lower()
        if role not in {"admin", "controller"}:
            self.send_json(403, {"error": "forbidden"}); return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request"}); return
        incident_id = str(payload.get("incident_id") or payload.get("id") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        if not incident_id or action not in {"acknowledge", "resolve"}:
            self.send_json(400, {"error": "invalid_request"}); return
        backend = _backend(legacy)
        repo = CustomerHealthRepository(backend)
        before = repo.get(incident_id)
        if before is None:
            self.send_json(404, {"error": "incident_not_found"}); return
        if role == "controller" and str(before.get("controller_id") or "") != str(user.get("scope_id") or ""):
            self.send_json(403, {"error": "forbidden"}); return
        try:
            result = repo.acknowledge(incident_id) if action == "acknowledge" else repo.resolve(incident_id)
        except ValueError as exc:
            self.send_json(409, {"error": str(exc)}); return
        ActivityAuditRepository(backend).record_action(
            actor_id=str(user.get("username") or user.get("id") or "") or None,
            actor_name=str(user.get("username") or user.get("id") or "operator"),
            actor_role=role,
            action=f"customer.health.{action}",
            category="customer-health",
            target_type="customer-health-incident",
            target_id=incident_id,
            target_name=str(before.get("message") or incident_id),
            result="success",
            summary=f"Customer health incident {action}: {incident_id}",
            changes={"state": {"before": before.get("state"), "after": (result or {}).get("state")}},
        )
        self.send_json(200, {"incident": result})

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = ["ADMIN_API", "ADMIN_ACTION_API", "CUSTOMER_API", "install_customer_health_http"]
