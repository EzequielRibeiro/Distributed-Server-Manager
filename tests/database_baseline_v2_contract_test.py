#!/usr/bin/env python3
"""Architecture guards for the migration-free Database Baseline v2."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from schema_baseline import load_schema_baseline, schema_path

BACKENDS = ("postgresql", "sqlite", "mysql", "mariadb")
HISTORICAL_SOURCE = re.compile(r"--\s*source:\s*[0-9]{3}_", re.IGNORECASE)
HISTORICAL_MIGRATION = re.compile(r"\bmigration\s+[0-9]{3}\b", re.IGNORECASE)


def _sql(backend: str) -> str:
    return load_schema_baseline(backend).sql


def test_baseline_source_files_exist():
    for backend in BACKENDS:
        path = schema_path(backend)
        assert path.is_file(), backend
        assert path.stat().st_size > 0, backend


def test_runtime_baselines_do_not_carry_historical_migration_narrative():
    offenders = []
    for backend in BACKENDS:
        sql = _sql(backend)
        if HISTORICAL_SOURCE.search(sql) or HISTORICAL_MIGRATION.search(sql):
            offenders.append(backend)
        if "schema_migrations" in sql.lower():
            offenders.append(backend + ":schema_migrations")
    assert not offenders, ", ".join(offenders)


def test_customers_are_declared_once_in_final_shape():
    offenders = []
    for backend in BACKENDS:
        sql = _sql(backend).lower()
        create_count = len(re.findall(r"create\s+table\s+customers\b", sql))
        alters = len(re.findall(r"alter\s+table\s+customers\b", sql))
        if create_count != 1 or alters != 0:
            offenders.append(f"{backend}(create={create_count}, alter={alters})")
    assert not offenders, ", ".join(offenders)


def test_customer_baseline_contract_tokens():
    required = (
        "customer_code",
        "customer_account_members",
        "service_contracts",
        "customer_invitations",
        "billing_provider",
        "billing_customer_id",
        "billing_status",
        "billing_synced_at",
        "customer_password_state",
    )
    for backend in BACKENDS:
        sql = _sql(backend).lower()
        for token in required:
            assert token in sql, f"{backend} missing {token}"


def test_system_user_functional_identity_exists_in_every_backend():
    required = (
        "full_name",
        "corporate_email",
        "phone",
        "job_title",
        "department",
        "created_by",
    )
    for backend in BACKENDS:
        sql = _sql(backend).lower()
        match = re.search(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?dashboard_users\s*\((.*?)\n\)",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        assert match is not None, f"{backend} missing dashboard_users"
        body = match.group(1)
        for token in required:
            assert token in body, f"{backend} dashboard_users missing {token}"
        assert re.search(r"corporate_email\s+[^,\n]+\s+unique\b", body), (
            f"{backend} corporate_email must be unique"
        )


def test_customer_relational_keys_are_numeric():
    for backend in BACKENDS:
        sql = _sql(backend)
        declarations = re.findall(
            r"\bcustomer_id\s+(BIGINT|INTEGER|TEXT|VARCHAR\s*\([^)]*\)|CHAR\s*\([^)]*\))",
            sql,
            re.IGNORECASE,
        )
        assert declarations, f"{backend} has no customer_id declarations"
        expected = "INTEGER" if backend == "sqlite" else "BIGINT"
        assert {item.upper() for item in declarations} == {expected}, (
            backend,
            declarations,
        )


def test_billing_identity_has_composite_uniqueness_and_atomic_pair_check():
    for backend in BACKENDS:
        normalized = re.sub(r"\s+", " ", _sql(backend).lower())
        assert re.search(
            r"unique\s*\(\s*billing_provider\s*,\s*billing_customer_id\s*\)",
            normalized,
        ), f"{backend} missing unique billing identity constraint"
        assert "ck_customers_billing_pair" in normalized


def test_dashboard_customer_scope_has_typed_fk():
    for backend in BACKENDS:
        normalized = re.sub(r"\s+", " ", _sql(backend).lower())
        expected = "integer" if backend == "sqlite" else "bigint"
        assert re.search(rf"customer_id\s+{expected}\b", normalized)
        assert "fk_dashboard_users_customer" in normalized
