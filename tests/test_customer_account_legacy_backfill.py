#!/usr/bin/env python3
"""Regression tests for legacy customer-account migration 019."""

from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MIGRATIONS = ROOT / "database" / "migrations"


def migration_sql(number: int) -> str:
    matches = sorted(MIGRATIONS.glob(f"{number:03d}_*.sql"))

    assert len(matches) == 1, (
        f"expected exactly one migration {number:03d}, "
        f"found {len(matches)}"
    )

    return matches[0].read_text(encoding="utf-8")


def apply(connection: sqlite3.Connection, number: int) -> None:
    connection.executescript(migration_sql(number))


def legacy_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    # Build the real schema through migration 018.
    for number in range(1, 19):
        apply(connection, number)

    return connection


def insert_customer(
    connection: sqlite3.Connection,
    *,
    customer_id: str,
    name: str,
    account_email: str | None,
) -> None:
    controller_id = "controller-test"

    # A tabela customers exige uma hierarquia válida:
    # node -> controller -> customer.
    connection.execute(
        """
        INSERT OR IGNORE INTO nodes (
            id,
            name,
            role,
            status
        )
        VALUES (?, ?, 'controller', 'active')
        """,
        (
            controller_id,
            "Controller Test",
        ),
    )

    connection.execute(
        """
        INSERT OR IGNORE INTO controllers (
            id,
            node_id,
            name,
            status
        )
        VALUES (?, ?, ?, 'active')
        """,
        (
            controller_id,
            controller_id,
            "Controller Test",
        ),
    )

    connection.execute(
        """
        INSERT INTO customers (
            id,
            controller_id,
            name,
            status,
            registration_status,
            account_email
        )
        VALUES (?, ?, ?, 'active', 'managed', ?)
        """,
        (
            customer_id,
            controller_id,
            name,
            account_email,
        ),
    )


def insert_customer_user(
    connection: sqlite3.Connection,
    *,
    username: str,
    customer_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO dashboard_users (
            username,
            password_hash,
            role,
            scope_id,
            active
        )
        VALUES (?, 'test-password-hash', 'customer', ?, 1)
        """,
        (
            username,
            customer_id,
        ),
    )


def test_019_backfills_legacy_customer_as_owner():
    connection = legacy_database()

    insert_customer(
        connection,
        customer_id="customer-aurora",
        name="Aurora",
        account_email="aurora@example.invalid",
    )
    insert_customer_user(
        connection,
        username="aurora",
        customer_id="customer-aurora",
    )

    before = connection.execute(
        """
        SELECT account_role
        FROM customer_account_members
        WHERE customer_id = ?
          AND username = ?
        """,
        ("customer-aurora", "aurora"),
    ).fetchone()

    assert before is None

    apply(connection, 19)

    membership = connection.execute(
        """
        SELECT customer_id, username, account_role
        FROM customer_account_members
        WHERE customer_id = ?
          AND username = ?
        """,
        ("customer-aurora", "aurora"),
    ).fetchone()

    assert membership is not None
    assert membership["customer_id"] == "customer-aurora"
    assert membership["username"] == "aurora"
    assert membership["account_role"] == "owner"


def test_019_backfills_owner_identity():
    connection = legacy_database()

    insert_customer(
        connection,
        customer_id="customer-aurora",
        name="Aurora",
        account_email="aurora@example.invalid",
    )
    insert_customer_user(
        connection,
        username="aurora",
        customer_id="customer-aurora",
    )

    apply(connection, 19)

    identity = connection.execute(
        """
        SELECT username, email
        FROM customer_user_identities
        WHERE username = ?
        """,
        ("aurora",),
    ).fetchone()

    assert identity is not None
    assert identity["username"] == "aurora"
    assert identity["email"] == "aurora@example.invalid"


def test_019_does_not_replace_existing_owner():
    connection = legacy_database()

    insert_customer(
        connection,
        customer_id="customer-a",
        name="Customer A",
        account_email="owner@example.invalid",
    )

    insert_customer_user(
        connection,
        username="existing-owner",
        customer_id="customer-a",
    )
    insert_customer_user(
        connection,
        username="legacy-user",
        customer_id="customer-a",
    )

    connection.execute(
        """
        INSERT INTO customer_account_members (
            customer_id,
            username,
            account_role
        )
        VALUES (?, ?, 'owner')
        """,
        ("customer-a", "existing-owner"),
    )

    apply(connection, 19)

    owner = connection.execute(
        """
        SELECT username
        FROM customer_account_members
        WHERE customer_id = ?
          AND account_role = 'owner'
        """,
        ("customer-a",),
    ).fetchall()

    assert [row["username"] for row in owner] == ["existing-owner"]

    legacy_membership = connection.execute(
        """
        SELECT account_role
        FROM customer_account_members
        WHERE customer_id = ?
          AND username = ?
        """,
        ("customer-a", "legacy-user"),
    ).fetchone()

    assert legacy_membership is None


def test_019_ignores_customer_user_with_invalid_scope():
    connection = legacy_database()

    connection.execute(
        """
        INSERT INTO dashboard_users (
            username,
            password_hash,
            role,
            scope_id,
            active
        )
        VALUES (?, 'test-password-hash', 'customer', ?, 1)
        """,
        ("orphan-user", "customer-does-not-exist"),
    )

    apply(connection, 19)

    membership = connection.execute(
        """
        SELECT customer_id, username
        FROM customer_account_members
        WHERE username = ?
        """,
        ("orphan-user",),
    ).fetchone()

    assert membership is None
