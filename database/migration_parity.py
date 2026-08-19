#!/usr/bin/env python3
"""Semantic parity checks for customer-account migrations across SQL backends."""
from __future__ import annotations
from pathlib import Path
BACKEND_DIRS={"sqlite":"migrations","postgresql":"migrations_postgresql","mysql":"migrations_mysql"}
CUSTOMER_MIGRATIONS=(
    "014_customer_account_identity.sql",
    "015_customer_account_access.sql",
    "016_customer_account_integrity.sql",
    "017_customer_user_identity_and_invitations.sql",
    "018_customer_email_verification.sql",
)
COMMON_MARKERS={
    "014_customer_account_identity.sql":("account_email","sftp_username","registration_status","email_verified_at"),
    "015_customer_account_access.sql":("customer_account_members","customer_password_recovery","owner","manager","member","token_hash","expires_at","consumed_at"),
    "016_customer_account_integrity.sql":("customer_account","owner"),
    "017_customer_user_identity_and_invitations.sql":("customer_user_identities","customer_invitations","customer_invitation_access","email_verified_at","token_hash","permission_profile"),
    "018_customer_email_verification.sql":("customer_email_verification","token_hash","expires_at","consumed_at"),
}
def validate_customer_migration_parity(database_root:Path)->list[str]:
    root=Path(database_root); errors=[]; contents={}
    for backend,directory in BACKEND_DIRS.items():
        contents[backend]={}
        for filename in CUSTOMER_MIGRATIONS:
            path=root/directory/filename
            if not path.is_file(): errors.append(f"{backend}: missing {filename}"); continue
            text=path.read_text(encoding="utf-8").lower(); contents[backend][filename]=text
            for marker in COMMON_MARKERS[filename]:
                if marker not in text: errors.append(f"{backend}: {filename} missing semantic marker {marker}")
    for backend,files in contents.items():
        combined="\n".join(files.values())
        if "customer_account_members" not in combined: errors.append(f"{backend}: customer membership model missing")
        if "customer_password_recovery" not in combined: errors.append(f"{backend}: recovery model missing")
        if "customer_user_identities" not in combined: errors.append(f"{backend}: per-login e-mail identity missing")
        if "customer_invitations" not in combined or "customer_invitation_access" not in combined: errors.append(f"{backend}: invitation model missing")
        if "customer_email_verification" not in combined: errors.append(f"{backend}: verification model missing")
        if backend=="mysql":
            if "uq_customer_account_owner" not in combined or "owner_customer_id" not in combined: errors.append("mysql: single-owner invariant missing")
        elif "idx_customer_account_owner" not in combined: errors.append(f"{backend}: single-owner invariant missing")
    return errors
def assert_customer_migration_parity(database_root:Path)->None:
    errors=validate_customer_migration_parity(database_root)
    if errors: raise RuntimeError("customer migration parity failed: "+"; ".join(errors))
