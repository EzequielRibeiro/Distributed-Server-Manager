#!/usr/bin/env python3
"""Backend-specific finalization for the Database Baseline v2 snapshot."""
from __future__ import annotations

import re


def finalize_baseline_sql(sql: str, backend: str) -> str:
    backend = str(backend or "").strip().lower()
    if backend not in {"mysql", "mariadb"}:
        return sql

    # MySQL explicitly forbids using an AUTO_INCREMENT column as a base column
    # of a generated column. MariaDB carries related limitations. For these
    # backends customer_code is therefore persisted by the repository after the
    # database allocates customers.id, inside the same transaction.
    sql, replaced = re.subn(
        r"customer_code\s+VARCHAR\(32\)\s+GENERATED\s+ALWAYS\s+AS\s+.*?\s+STORED\s+UNIQUE,",
        "customer_code VARCHAR(32) UNIQUE,",
        sql,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if replaced != 1:
        raise ValueError(f"{backend} baseline customer_code shape was not normalized")

    # Keep the same insert contract used by Customer repositories: metadata is
    # always available even when callers do not provide it explicitly.
    sql, metadata_replaced = re.subn(
        r"metadata_json\s+JSON\s+NOT\s+NULL,",
        "metadata_json LONGTEXT NOT NULL DEFAULT ('{}'),\n    CONSTRAINT chk_customers_metadata_json CHECK (JSON_VALID(metadata_json)),",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if metadata_replaced != 1:
        raise ValueError(f"{backend} baseline customer metadata shape was not normalized")
    return sql


__all__ = ["finalize_baseline_sql"]
