#!/usr/bin/env python3
"""Semantic parity checks across consolidated backend schemas."""
from __future__ import annotations
from pathlib import Path
BACKEND_SCHEMAS={"sqlite":"sqlite.sql","postgresql":"postgresql.sql","mysql":"mysql.sql","mariadb":"mariadb.sql"}
COMMON_MARKERS=("account_email","sftp_username","registration_status","email_verified_at",
    "customer_account_members","customer_password_recovery","owner","manager","member",
    "token_hash","expires_at","consumed_at","customer_user_identities","customer_invitations",
    "customer_invitation_access","permission_profile","customer_email_verification")
def validate_customer_schema_parity(database_root:Path)->list[str]:
    root=Path(database_root); errors=[]; contents={}
    for backend,filename in BACKEND_SCHEMAS.items():
        path=root/"schemas"/filename
        if not path.is_file(): errors.append(f"{backend}: missing {filename}"); continue
        combined=path.read_text(encoding="utf-8").lower(); contents[backend]=combined
        for marker in COMMON_MARKERS:
            if marker not in combined: errors.append(f"{backend}: schema missing semantic marker {marker}")
    for backend,combined in contents.items():
        if "customer_account_members" not in combined: errors.append(f"{backend}: customer membership model missing")
        if "customer_password_recovery" not in combined: errors.append(f"{backend}: recovery model missing")
        if "customer_user_identities" not in combined: errors.append(f"{backend}: per-login e-mail identity missing")
        if "customer_invitations" not in combined or "customer_invitation_access" not in combined: errors.append(f"{backend}: invitation model missing")
        if "customer_email_verification" not in combined: errors.append(f"{backend}: verification model missing")
        if backend in {"mysql","mariadb"}:
            if "uq_customer_account_owner" not in combined or "owner_customer_id" not in combined: errors.append("mysql: single-owner invariant missing")
        elif "idx_customer_account_owner" not in combined: errors.append(f"{backend}: single-owner invariant missing")
    return errors
def assert_customer_schema_parity(database_root:Path)->None:
    errors=validate_customer_schema_parity(database_root)
    if errors: raise RuntimeError("customer schema parity failed: "+"; ".join(errors))
