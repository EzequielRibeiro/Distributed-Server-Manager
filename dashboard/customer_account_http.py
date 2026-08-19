#!/usr/bin/env python3
"""HTTP-neutral dispatcher for customer self-service account flows."""
from __future__ import annotations

import os
import re
import uuid
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from customer_account_api import member_capabilities, registration_payload, require_customer, require_member_management
from customer_account_repository import CustomerAccountRepository
from customer_auth_api import CUSTOMER_AUTH_PATHS, dispatch_customer_auth
from customer_identity import CustomerIdentityService, normalize_email, sftp_username_seed
from customer_team_api import CUSTOMER_TEAM_PATHS, dispatch_customer_team
from customer_team_repository import CustomerTeamRepository
from user_repository import UserRepository
from users import hash_password

PUBLIC_PATHS = {
    "/api/customer/register",
    "/api/customer/password-recovery",
    "/api/customer/password-reset",
}
LEGACY_TEAM_PATHS = {"/api/customer/members"}
AUTHENTICATED_PATHS = CUSTOMER_AUTH_PATHS | CUSTOMER_TEAM_PATHS | LEGACY_TEAM_PATHS


def _username_for_email(session: AlertSession, dialect, email: str) -> str:
    seed = sftp_username_seed(email); ph = dialect.placeholder
    for attempt in range(101):
        candidate = seed if attempt == 0 else f"{seed[:22].rstrip('-._')}-{uuid.uuid5(uuid.NAMESPACE_URL, email+str(attempt)).hex[:8]}"
        if session.execute(f"SELECT 1 FROM dashboard_users WHERE username={ph}", (candidate,)).fetchone() is None:
            return candidate
    raise RuntimeError("unable to allocate customer username")


def _default_controller(session: AlertSession) -> str:
    configured = os.environ.get("DSM_CUSTOMER_REGISTRATION_CONTROLLER", "").strip()
    ph = session.dialect.placeholder
    if configured:
        row = session.execute(f"SELECT id FROM controllers WHERE id={ph} AND status='active'", (configured,)).fetchone()
        if row is None: raise ValueError("customer registration controller is unavailable")
        return configured
    rows = session.execute("SELECT id FROM controllers WHERE status='active' ORDER BY id LIMIT 2").fetchall()
    if len(rows) != 1: raise ValueError("customer registration requires a configured controller")
    return str(rows[0]["id"])


def register_customer(payload: dict[str, Any], backend) -> dict[str, Any]:
    request = registration_payload(payload, normalize_email); backend.initialize(); dialect = dialect_for_backend(backend); ph = dialect.placeholder
    customer_id = f"customer-{uuid.uuid4().hex[:16]}"
    with backend.transaction() as connection:
        session = AlertSession(backend, connection)
        try:
            duplicate = session.execute(f"SELECT 1 FROM customers WHERE LOWER(account_email)=LOWER({ph}) OR LOWER(email)=LOWER({ph})", (request["email"], request["email"])).fetchone()
            if duplicate is not None: raise ValueError("customer account email already registered")
            controller_id = _default_controller(session); username = _username_for_email(session, dialect, request["email"])
            sftp_username = CustomerIdentityService(backend).allocate_sftp_username(session, request["email"])
            session.execute("INSERT INTO customers(id,controller_id,name,email,phone,status,legal_name,document_type,document_number,account_email,sftp_username,registration_status) "
                            f"VALUES ({dialect.parameters(12)})", (customer_id, controller_id, request["name"], request["email"], request["phone"] or None, "active", request["name"], request["document_type"] or None, request["document_number"] or None, request["email"], sftp_username, "active"))
            session.execute("INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) "
                            f"VALUES ({dialect.parameters(4)},TRUE)", (username, hash_password(request["password"]), "customer", customer_id))
            session.execute("INSERT INTO customer_account_members(customer_id,username,account_role) "
                            f"VALUES ({dialect.parameters(3)})", (customer_id, username, "owner"))
        finally: session.close()
    return {"customer_id": customer_id, "username": username, "sftp_username": sftp_username, "registration_status": "active"}


def request_recovery(payload: dict[str, Any], backend) -> dict[str, Any]:
    email = normalize_email(payload.get("email")); backend.initialize(); dialect = dialect_for_backend(backend); ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute("SELECT u.username FROM dashboard_users u JOIN customers c ON c.id=u.scope_id "
                                  f"WHERE u.role='customer' AND u.active=TRUE AND (LOWER(c.account_email)=LOWER({ph}) OR LOWER(c.email)=LOWER({ph})) ORDER BY u.username LIMIT 1", (email, email)).fetchone()
        finally: session.close()
    result = {"accepted": True}
    if row is not None:
        token = CustomerAccountRepository(backend).create_recovery(str(row["username"]))
        if os.environ.get("DSM_CUSTOMER_RECOVERY_EXPOSE_TOKEN", "").lower() in {"1","true","yes"}: result["recovery_token"] = token
    return result


def reset_password(payload: dict[str, Any], backend) -> dict[str, Any]:
    token = str(payload.get("token", "")).strip(); password = str(payload.get("password", ""))
    if not token: raise ValueError("recovery token is required")
    password_hash = hash_password(password)
    username = CustomerAccountRepository(backend).consume_recovery(token)
    UserRepository(backend).change_password(username, password_hash)
    return {"reset": True}


def _legacy_members(method: str, body: dict[str, Any], user, backend):
    """Compatibility adapter for the pre-4.3Q /api/customer/members contract."""
    if method == "GET":
        return dispatch_customer_team("GET", "/api/customer/team", payload=None, user=user, backend=backend)
    if method != "POST":
        return 405, {"error": "method not allowed"}
    action = str(body.get("action", "link")).strip().lower()
    if action == "create": path = "/api/customer/team/members/create"
    elif action == "role": path = "/api/customer/team/members/role"
    elif action == "remove": path = "/api/customer/team/members/remove"
    elif action == "access": path = "/api/customer/team/access"
    elif action == "link":
        username, customer_id = require_customer(user)
        repository = CustomerTeamRepository(backend)
        actor_role = repository.account_role(customer_id, username)
        if actor_role is None: raise PermissionError("customer account membership is required")
        require_member_management(actor_role)
        target = str(body.get("username", "")).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", target): raise ValueError("invalid username")
        CustomerAccountRepository(backend).set_member(customer_id, target, str(body.get("account_role", "member")).strip().lower())
        return dispatch_customer_team("GET", "/api/customer/team", payload=None, user=user, backend=backend)
    else:
        return 400, {"error": "invalid customer team action"}
    return dispatch_customer_team("POST", path, payload=body, user=user, backend=backend)


def dispatch_customer_account(method: str, path: str, *, payload: dict[str, Any] | None, user: dict[str, Any] | None, backend) -> tuple[int, dict[str, Any]] | None:
    body = payload or {}
    if path in CUSTOMER_AUTH_PATHS:
        return dispatch_customer_auth(method, path, user=user, backend=backend)
    if path in CUSTOMER_TEAM_PATHS:
        return dispatch_customer_team(method, path, payload=body, user=user, backend=backend)
    if path in LEGACY_TEAM_PATHS:
        try:
            return _legacy_members(method, body, user, backend)
        except PermissionError as exc: return 403, {"error": str(exc)}
        except (ValueError, LookupError) as exc: return 400, {"error": str(exc)}
    if path not in PUBLIC_PATHS:
        return None
    try:
        if path == "/api/customer/register" and method == "POST": return 201, register_customer(body, backend)
        if path == "/api/customer/password-recovery" and method == "POST": return 202, request_recovery(body, backend)
        if path == "/api/customer/password-reset" and method == "POST": return 200, reset_password(body, backend)
        return 405, {"error": "method not allowed"}
    except PermissionError as exc: return 403, {"error": str(exc)}
    except (ValueError, LookupError) as exc: return 400, {"error": str(exc)}
    except Exception: return 500, {"error": "customer account operation failed"}
