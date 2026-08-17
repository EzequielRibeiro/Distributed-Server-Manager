#!/usr/bin/env python3
# =============================================================
# Capivara DSM
#
# Arquivo: database/customers.py
# File: database/customers.py
#
# Administração e consulta de clientes.
# Customer administration and queries.
# =============================================================

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from backend import DatabaseBackend, DatabaseConfig
from backend_factory import create_backend
from customer_repository import CustomerRepository


DOCUMENT_RE = re.compile(r"\D+")


def database_connection(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def normalize_document(value):
    """Remove formatting from CPF/CNPJ or other numeric documents."""
    return DOCUMENT_RE.sub("", str(value or ""))


def mask_document(document_type, document_number):
    """Return a document safe for presentation in the dashboard."""

    digits = normalize_document(document_number)

    if not digits:
        return None

    if document_type == "cpf" and len(digits) == 11:
        return f"***.***.***-{digits[-2:]}"

    if document_type == "cnpj" and len(digits) == 14:
        return f"**.***.***/****-{digits[-2:]}"

    if len(digits) <= 4:
        return "*" * len(digits)

    return ("*" * (len(digits) - 4)) + digits[-4:]


def customer_to_public(row):
    """Convert a customer row without exposing the raw document."""

    data = dict(row)

    document_number = data.pop(
        "document_number",
        None,
    )

    data["document"] = mask_document(
        data.get("document_type"),
        document_number,
    )

    return data


def _legacy_search_customers(
    database_path,
    *,
    query="",
    status="",
    limit=50,
    offset=0,
):
    """Search customers using the administrative customer directory.

    Returns the current page together with pagination metadata.
    """

    query = str(query or "").strip()
    status = str(status or "").strip()

    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid pagination") from exc

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    conditions = []
    parameters = []
    where_sql = ""

    if query:
        like = f"%{query}%"

        search_conditions = [
            "c.id LIKE ?",
            "c.name LIKE ?",
            "COALESCE(c.legal_name, '') LIKE ?",
            "COALESCE(c.email, '') LIKE ?",
            "COALESCE(c.phone, '') LIKE ?",
            "COALESCE(c.billing_customer_id, '') LIKE ?",
        ]

        search_parameters = [
            like,
            like,
            like,
            like,
            like,
            like,
        ]

        document = normalize_document(query)

        if len(document) >= 4:
            search_conditions.append(
                "COALESCE(c.document_number, '') LIKE ?"
            )
            search_parameters.append(
                f"%{document}%"
            )

        conditions.append(
            "("
            + " OR ".join(search_conditions)
            + ")"
        )

        parameters.extend(
            search_parameters
        )


    # ---------------------------------------------------------
    # Total number of customers matching the filters.
    # ---------------------------------------------------------
    if status:
        allowed_statuses = {
            "active",
            "suspended",
            "cancelled",
        }

        if status not in allowed_statuses:
            raise ValueError("invalid customer status")

        conditions.append("c.status = ?")
        parameters.append(status)

    # Build WHERE clause from all active filters.
    if conditions:
        where_sql = "WHERE " + " AND ".join(conditions)
    count_sql = f"""
        SELECT COUNT(*)
        FROM customers c
        {where_sql}
    """

    # ---------------------------------------------------------
    # Current page.
    # ---------------------------------------------------------
    search_sql = f"""
        SELECT
            c.id,
            c.controller_id,
            c.name,
            c.legal_name,
            c.email,
            c.phone,
            c.document_type,
            c.document_number,
            c.status,

            c.billing_provider,
            c.billing_customer_id,
            c.billing_status,
            c.billing_synced_at,

            c.created_at,
            c.updated_at,

            COUNT(DISTINCT i.id)
                AS instance_count,

            COUNT(DISTINCT sc.id)
                AS contract_count,

            COUNT(
                DISTINCT CASE
                    WHEN du.active = 1
                    THEN du.username
                END
            ) AS user_count

        FROM customers c

        LEFT JOIN instances i
            ON i.customer_id = c.id

        LEFT JOIN service_contracts sc
            ON sc.customer_id = c.id

        LEFT JOIN dashboard_users du
            ON du.role = 'customer'
            AND du.scope_id = c.id

        {where_sql}

        GROUP BY c.id

        ORDER BY
            c.name COLLATE NOCASE,
            c.id

        LIMIT ?
        OFFSET ?
    """

    with closing(
        database_connection(database_path)
    ) as connection:

        total = connection.execute(
            count_sql,
            parameters,
        ).fetchone()[0]

        rows = connection.execute(
            search_sql,
            [
                *parameters,
                limit,
                offset,
            ],
        ).fetchall()

    items = [
        customer_to_public(row)
        for row in rows
    ]

    return {
        "items": items,
        "total": total,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


def _legacy_get_customer(
    database_path,
    customer_id,
):
    """Return the complete administrative view of one customer."""

    customer_id = str(
        customer_id or ""
    ).strip()

    if not customer_id:
        return None

    with closing(
        database_connection(database_path)
    ) as connection:

        customer = connection.execute(
            """
            SELECT
                c.id,
                c.controller_id,
                c.name,
                c.legal_name,
                c.email,
                c.phone,
                c.document_type,
                c.document_number,
                c.status,

                c.billing_provider,
                c.billing_customer_id,
                c.billing_status,
                c.billing_synced_at,

                c.created_at,
                c.updated_at,

                ctrl.name AS controller_name,
                ctrl.status AS controller_status

            FROM customers c

            LEFT JOIN controllers ctrl
                ON ctrl.id = c.controller_id

            WHERE c.id = ?
            """,
            (customer_id,),
        ).fetchone()

        if customer is None:
            return None

        users = connection.execute(
            """
            SELECT
                username,
                role,
                active,
                created_at,
                updated_at

            FROM dashboard_users

            WHERE
                role = 'customer'
                AND scope_id = ?

            ORDER BY username
            """,
            (customer_id,),
        ).fetchall()

        contracts = connection.execute(
            """
            SELECT
                sc.id,
                sc.game_id,
                sc.status,
                sc.instance_limit,
                sc.starts_at,
                sc.ends_at,
                sc.created_at,

                COUNT(ic.instance_id)
                    AS instances_used

            FROM service_contracts sc

            LEFT JOIN instance_contracts ic
                ON ic.contract_id = sc.id

            WHERE sc.customer_id = ?

            GROUP BY sc.id

            ORDER BY
                sc.created_at DESC,
                sc.id
            """,
            (customer_id,),
        ).fetchall()

        instances = connection.execute(
            """
            SELECT
                i.id,
                i.node_id,
                i.game_id,
                i.name,
                i.status,
                i.controller_id,
                i.agent_id,
                i.customer_id,
                i.created_at,

                a.name AS agent_name,
                a.status AS agent_status,

                ic.contract_id

            FROM instances i

            LEFT JOIN agents a
                ON a.id = i.agent_id

            LEFT JOIN instance_contracts ic
                ON ic.instance_id = i.id

            WHERE i.customer_id = ?

            ORDER BY
                i.name COLLATE NOCASE,
                i.id
            """,
            (customer_id,),
        ).fetchall()

        permissions = connection.execute(
            """
            SELECT
                ia.username,
                ia.instance_id,
                ia.permission_profile

            FROM instance_access ia

            INNER JOIN dashboard_users du
                ON du.username = ia.username

            WHERE
                du.role = 'customer'
                AND du.scope_id = ?

            ORDER BY
                ia.username,
                ia.instance_id
            """,
            (customer_id,),
        ).fetchall()

        audit_rows = connection.execute(
            """
            SELECT
                al.username,
                al.instance_id,
                al.action,
                al.result,
                al.details

            FROM audit_log al

            WHERE
                al.username IN (
                    SELECT username

                    FROM dashboard_users

                    WHERE
                        role = 'customer'
                        AND scope_id = ?
                )

                OR al.instance_id IN (
                    SELECT id

                    FROM instances

                    WHERE customer_id = ?
                )

            ORDER BY rowid DESC

            LIMIT 100
            """,
            (
                customer_id,
                customer_id,
            ),
        ).fetchall()

    result = customer_to_public(
        customer
    )

    result["users"] = [
        dict(row)
        for row in users
    ]

    result["contracts"] = [
        dict(row)
        for row in contracts
    ]

    result["instances"] = [
        dict(row)
        for row in instances
    ]

    result["permissions"] = [
        dict(row)
        for row in permissions
    ]

    result["audit"] = [
        dict(row)
        for row in audit_rows
    ]

    return result


# =============================================================
# Multi-database compatibility facade
#
# Keep the historical implementation above temporarily for an
# easily reviewable transition. These final public definitions are
# authoritative and delegate every query to CustomerRepository.
# =============================================================

def _repository(
    target: str | Path | DatabaseBackend,
) -> CustomerRepository:
    if isinstance(target, DatabaseBackend):
        return CustomerRepository(target)

    return CustomerRepository(
        create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(
                    Path(target).expanduser().resolve()
                ),
            )
        )
    )


def search_customers(
    database_path: str | Path | DatabaseBackend,
    *,
    query="",
    status="",
    limit=50,
    offset=0,
):
    """Search customers through CustomerRepository."""

    return _repository(database_path).search_customers(
        query=query,
        status=status,
        limit=limit,
        offset=offset,
    )


def get_customer(
    database_path: str | Path | DatabaseBackend,
    customer_id,
):
    """Return a customer view through CustomerRepository."""

    return _repository(database_path).get_customer(
        customer_id
    )
