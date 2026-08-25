#!/usr/bin/env python3
"""Customer-only Basic authentication accepting username or verified e-mail."""
from __future__ import annotations

import base64

from alert_repository import AlertSession, dialect_for_backend
from users import verify_password


def authenticate_customer(headers, backend):
    raw = str(headers.get("Authorization", "")) if headers is not None else ""
    if not raw.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(raw[6:].strip(), validate=True).decode("utf-8")
        login, password = decoded.split(":", 1)
    except Exception:
        return None
    login = login.strip().lower()
    if not login:
        return None
    backend.initialize()
    ph = dialect_for_backend(backend).placeholder
    select = (
        "SELECT u.username,u.password_hash,u.role,u.customer_id,u.active,c.customer_code "
        "FROM dashboard_users u JOIN customers c ON c.id=u.customer_id "
    )
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            if "@" in login:
                row = session.execute(
                    select + "JOIN customer_user_identities i ON i.username=u.username "
                    f"WHERE LOWER(i.email)=LOWER({ph}) AND i.email_verified_at IS NOT NULL",
                    (login,),
                ).fetchone()
            else:
                row = session.execute(
                    select + f"WHERE u.username={ph}",
                    (login,),
                ).fetchone()
            if (
                row is None
                or row["role"] != "customer"
                or row["customer_id"] is None
                or not row["active"]
            ):
                return None
            if not verify_password(password, str(row["password_hash"])):
                return None
            customer_id = int(row["customer_id"])
            customer_code = str(row["customer_code"])
            return {
                "username": str(row["username"]),
                "role": "customer",
                "customer_id": customer_id,
                "customer_code": customer_code,
                # Legacy dashboard helpers still accept scope_id. Keep that
                # compatibility value numeric; the public CLI-* identity stays
                # exclusively in customer_code.
                "scope_id": customer_id,
                "active": True,
            }
        finally:
            session.close()
