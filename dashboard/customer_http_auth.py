#!/usr/bin/env python3
"""Customer-only Basic authentication accepting username or verified e-mail."""
from __future__ import annotations
import base64
from alert_repository import AlertSession,dialect_for_backend
from users import verify_password

def authenticate_customer(headers, backend):
    raw=str(headers.get("Authorization", "")) if headers is not None else ""
    if not raw.startswith("Basic "):
        return None
    try:
        decoded=base64.b64decode(raw[6:].strip(),validate=True).decode("utf-8")
        login,password=decoded.split(":",1)
    except Exception:
        return None
    login=login.strip().lower()
    if not login:
        return None
    backend.initialize(); ph=dialect_for_backend(backend).placeholder
    with backend.connect() as connection:
        s=AlertSession(backend,connection)
        try:
            if "@" in login:
                row=s.execute(
                    "SELECT u.username,u.password_hash,u.role,u.scope_id,u.active FROM customer_user_identities i "
                    "JOIN dashboard_users u ON u.username=i.username "
                    f"WHERE LOWER(i.email)=LOWER({ph}) AND i.email_verified_at IS NOT NULL",
                    (login,),
                ).fetchone()
            else:
                row=s.execute(
                    f"SELECT username,password_hash,role,scope_id,active FROM dashboard_users WHERE username={ph}",
                    (login,),
                ).fetchone()
            if row is None or row["role"]!="customer" or not row["active"]:
                return None
            if not verify_password(password,str(row["password_hash"])):
                return None
            return {"username":str(row["username"]),"role":"customer","scope_id":str(row["scope_id"]),"active":True}
        finally:s.close()
