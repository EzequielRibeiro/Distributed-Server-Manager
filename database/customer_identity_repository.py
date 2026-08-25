#!/usr/bin/env python3
"""Persistence helper for Database Baseline v2 Customer identities.

Customer primary keys are allocated by the database.  The public Customer code
is derived exclusively from that primary key and is never supplied by callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from customer_code import format_customer_code


@dataclass(frozen=True)
class CreatedCustomerIdentity:
    id: int
    customer_code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "customer_code": self.customer_code,
        }


def _positive_id(value: Any) -> int:
    if isinstance(value, bool):
        raise RuntimeError("database returned an invalid customer id")
    try:
        customer_id = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("database returned an invalid customer id") from exc
    if customer_id <= 0:
        raise RuntimeError("database returned an invalid customer id")
    return customer_id


def _identity(customer_id: Any) -> CreatedCustomerIdentity:
    numeric_id = _positive_id(customer_id)
    return CreatedCustomerIdentity(
        id=numeric_id,
        customer_code=format_customer_code(numeric_id),
    )


def insert_customer(
    session: Any,
    *,
    backend_name: str,
    parameters: str,
    controller_id: str,
    name: str,
    email: str | None,
    phone: str | None,
    status: str = "active",
) -> CreatedCustomerIdentity:
    """Insert a Customer and return its database-generated identity.

    PostgreSQL uses RETURNING so allocation and retrieval are one atomic
    statement. SQLite/MySQL/MariaDB use the cursor's lastrowid from the same
    INSERT statement.  No MAX(id), COUNT(*) or reusable application counter is
    permitted.
    """

    values = (controller_id, name, email, phone, status)
    base_sql = (
        "INSERT INTO customers(controller_id,name,email,phone,status) "
        f"VALUES ({parameters})"
    )

    backend = str(backend_name or "").strip().lower()
    if backend == "postgresql":
        row = session.execute(base_sql + " RETURNING id", values).fetchone()
        if row is None:
            raise RuntimeError("database did not return the new customer id")
        return _identity(row["id"])

    cursor = session.execute(base_sql, values)
    customer_id = getattr(cursor, "lastrowid", None)
    if customer_id is None:
        raise RuntimeError("database driver did not expose the new customer id")
    return _identity(customer_id)


def public_customer_reference(customer_id: Any) -> dict[str, Any]:
    """Return the canonical API/UI identity pair for an existing Customer."""
    return _identity(customer_id).as_dict()


__all__ = [
    "CreatedCustomerIdentity",
    "insert_customer",
    "public_customer_reference",
]
