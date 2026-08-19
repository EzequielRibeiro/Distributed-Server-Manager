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
from customer_identity import CustomerIdentityService, normalize_email, sftp_username_seed
from user_repository import UserRepository
from users import hash_password

PUBLIC_PATHS = {"/api/customer/register", "/api/customer/password-recovery", "/api/customer/password-reset"}
AUTHENTICATED_PATHS = {"/api/customer/members"}


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


def _actor_role(repository: CustomerAccountRepository, customer_id: str, username: str) -> str:
    for member in repository.list_members(customer_id):
        if member["username"] == username: return str(member["account_role"])
    raise PermissionError("customer account membership is required")


def dispatch_customer_account(method: str, path: str, *, payload: dict[str, Any] | None, user: dict[str, Any] | None, backend) -> tuple[int, dict[str, Any]] | None:
    if path not in PUBLIC_PATHS | AUTHENTICATED_PATHS: return None
    body = payload or {}
    try:
        if path == "/api/customer/register" and method == "POST": return 201, register_customer(body, backend)
        if path == "/api/customer/password-recovery" and method == "POST": return 202, request_recovery(body, backend)
        if path == "/api/customer/password-reset" and method == "POST": return 200, reset_password(body, backend)
        if path == "/api/customer/members":
            username, customer_id = require_customer(user); repository = CustomerAccountRepository(backend); actor_role = _actor_role(repository, customer_id, username)
            if method == "GET": return 200, {"members": repository.list_members(customer_id), "capabilities": member_capabilities(actor_role)}
            if method == "POST":
                require_member_management(actor_role); target = str(body.get("username", "")).strip().lower(); role = str(body.get("account_role", "member")).strip().lower()
                if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", target): raise ValueError("invalid username")
                repository.set_member(customer_id, target, role); return 200, {"saved": True}
        return 405, {"error": "method not allowed"}
    except PermissionError as exc: return 403, {"error": str(exc)}
    except (ValueError, LookupError) as exc: return 400, {"error": str(exc)}
    except Exception: return 500, {"error": "customer account operation failed"}
