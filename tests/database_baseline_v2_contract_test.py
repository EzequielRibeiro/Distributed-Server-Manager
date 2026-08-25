#!/usr/bin/env python3
"""Architecture guards for the migration-free Database Baseline v2."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "database" / "schemas"
BACKENDS = ("postgresql.sql", "sqlite.sql", "mysql.sql", "mariadb.sql")

HISTORICAL_SOURCE = re.compile(r"--\s*source:\s*[0-9]{3}_", re.IGNORECASE)
HISTORICAL_MIGRATION = re.compile(r"\bmigration\s+[0-9]{3}\b", re.IGNORECASE)


def _sql(name: str) -> str:
    return (SCHEMAS / name).read_text(encoding="utf-8")


def test_baseline_files_exist():
    for name in BACKENDS:
        path = SCHEMAS / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


@pytest.mark.xfail(
    strict=True,
    reason="exit criterion: rewrite all four schemas as migration-free baselines",
)
def test_final_baselines_must_not_carry_historical_source_markers():
    offenders = []
    for name in BACKENDS:
        sql = _sql(name)
        if HISTORICAL_SOURCE.search(sql) or HISTORICAL_MIGRATION.search(sql):
            offenders.append(name)
    assert not offenders, (
        "Database Baseline v2 still contains historical migration narrative: "
        + ", ".join(offenders)
    )


@pytest.mark.xfail(
    strict=True,
    reason="exit criterion: customers must be declared directly in final shape",
)
def test_customer_table_is_created_in_final_shape_once():
    offenders = []
    for name in BACKENDS:
        sql = _sql(name).lower()
        create_count = len(re.findall(r"create\s+table\s+customers\b", sql))
        alters = len(re.findall(r"alter\s+table\s+customers\b", sql))
        if create_count != 1 or alters != 0:
            offenders.append(f"{name}(create={create_count}, alter={alters})")
    assert not offenders, (
        "customers must be declared once in final shape with no historical ALTERs: "
        + ", ".join(offenders)
    )


@pytest.mark.xfail(
    strict=True,
    reason="exit criterion: customer_code must exist in every backend baseline",
)
def test_customer_baseline_contract_tokens():
    required = (
        "customer_code",
        "customer_account_members",
        "service_contracts",
        "customer_invitations",
    )
    for name in BACKENDS:
        sql = _sql(name).lower()
        for token in required:
            assert token in sql, f"{name} missing {token}"
