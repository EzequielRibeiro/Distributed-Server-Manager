#!/usr/bin/env python3
"""Semantic parity checks for customer-account migrations across SQL backends."""
from __future__ import annotations

from pathlib import Path

BACKEND_DIRS = {
    "sqlite": "migrations",
    "postgresql": "migrations_postgresql",
    "mysql": "migrations_mysql",
}
CUSTOMER_MIGRATIONS = (
    "014_customer_account_identity.sql",
    "015_customer_account_access.sql",
    "016_customer_account_integrity.sql",
)
COMMON_MARKERS = {
    "014_customer_account_identity.sql": (
        "account_email", "sftp_username", "registration_status", "email_verified_at",
    ),
    "015_customer_account_access.sql": (
        "customer_account_members", "customer_password_recovery", "owner", "manager", "member", "token_hash", "expires_at", "consumed_at",
    ),
    "016_customer_account_integrity.sql": (
        "customer_account", "owner",
    ),
}


def validate_customer_migration_parity(database_root: Path) -> list[str]:
    root = Path(database_root)
    errors: list[str] = []
    contents: dict[str, dict[str, str]] = {}
    for backend, directory in BACKEND_DIRS.items():
        contents[backend] = {}
        for filename in CUSTOMER_MIGRATIONS:
            path = root / directory / filename
            if not path.is_file():
                errors.append(f"{backend}: missing {filename}")
                continue
            text = path.read_text(encoding="utf-8").lower()
            contents[backend][filename] = text
            for marker in COMMON_MARKERS[filename]:
                if marker.lower() not in text:
                    errors.append(f"{backend}: {filename} missing semantic marker {marker}")

    for backend, files in contents.items():
        combined = "\n".join(files.values())
        if "customer_account_members" not in combined:
            errors.append(f"{backend}: customer membership model missing")
        if "customer_password_recovery" not in combined:
            errors.append(f"{backend}: recovery model missing")
        if "viewer" in combined or "operator" in combined:
            # Account migrations must not redefine per-instance profiles.
            errors.append(f"{backend}: customer account migrations mix instance profiles with account roles")
        if backend == "mysql":
            if "uq_customer_account_owner" not in combined or "owner_customer_id" not in combined:
                errors.append("mysql: single-owner invariant missing")
        elif "idx_customer_account_owner" not in combined:
            errors.append(f"{backend}: single-owner invariant missing")
    return errors


def assert_customer_migration_parity(database_root: Path) -> None:
    errors = validate_customer_migration_parity(database_root)
    if errors:
        raise RuntimeError("customer migration parity failed: " + "; ".join(errors))
