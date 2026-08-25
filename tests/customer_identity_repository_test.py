from __future__ import annotations

from types import SimpleNamespace

import pytest

from database.customer_identity_repository import (
    insert_customer,
    public_customer_reference,
)


class RowCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class PostgreSQLSession:
    def __init__(self, customer_id: int):
        self.customer_id = customer_id
        self.calls = []

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))
        return RowCursor({"id": self.customer_id})


class LastRowIdSession:
    def __init__(self, customer_id: int | None):
        self.customer_id = customer_id
        self.calls = []

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))
        return SimpleNamespace(lastrowid=self.customer_id)


def _create(session, backend_name="postgresql", **kwargs):
    return insert_customer(
        session,
        backend_name=backend_name,
        parameters="%s,%s,%s,%s,%s,%s,%s,%s",
        controller_id="controller-1",
        name="Aurora",
        email="aurora@example.invalid",
        phone=None,
        **kwargs,
    )


def test_postgresql_uses_returning_and_formats_public_code():
    session = PostgreSQLSession(27)
    created = _create(session)
    assert created.id == 27
    assert created.customer_code == "CLI-000027"
    assert created.billing.linked is False
    assert "RETURNING id" in session.calls[0][0]
    assert "customers(id" not in session.calls[0][0].lower()


def test_sqlite_mysql_family_uses_lastrowid():
    for backend in ("sqlite", "mysql", "mariadb"):
        session = LastRowIdSession(8)
        created = _create(session, backend)
        assert created.id == 8
        assert created.customer_code == "CLI-000008"
        assert "RETURNING" not in session.calls[0][0]


def test_no_customer_id_is_part_of_insert_parameters():
    session = PostgreSQLSession(101)
    _create(session)
    sql, parameters = session.calls[0]
    assert sql.startswith("INSERT INTO customers(controller_id,name,email,phone,status,")
    assert parameters == (
        "controller-1",
        "Aurora",
        "aurora@example.invalid",
        None,
        "active",
        None,
        None,
        None,
    )


def test_billing_identity_is_inserted_atomically_with_customer():
    session = PostgreSQLSession(52)
    created = _create(
        session,
        billing_provider="Stripe",
        billing_customer_id="cus_ABC123",
        billing_status="active",
    )
    sql, parameters = session.calls[0]
    assert "billing_provider,billing_customer_id,billing_status" in sql
    assert parameters[-3:] == ("stripe", "cus_ABC123", "active")
    assert created.as_dict()["billing"] == {
        "provider": "stripe",
        "customer_id": "cus_ABC123",
        "status": "active",
        "linked": True,
    }


def test_partial_billing_identity_is_rejected_before_insert():
    session = PostgreSQLSession(53)
    with pytest.raises(ValueError, match="supplied together"):
        _create(session, billing_provider="stripe")
    assert session.calls == []


def test_missing_lastrowid_is_rejected():
    with pytest.raises(RuntimeError, match="did not expose"):
        _create(LastRowIdSession(None), "sqlite")


def test_public_reference_is_derived_from_primary_key():
    assert public_customer_reference(345) == {
        "id": 345,
        "customer_code": "CLI-000345",
    }
