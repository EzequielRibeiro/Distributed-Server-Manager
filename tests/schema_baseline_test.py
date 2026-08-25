#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from schema_baseline import (
    BASELINE_NAME,
    baseline_marker_sql,
    load_schema_baseline,
    normalize_backend_name,
    schema_path,
)


def test_backend_alias_and_paths():
    assert normalize_backend_name("postgres") == "postgresql"
    assert normalize_backend_name("PostgreSQL") == "postgresql"
    assert schema_path("sqlite").name == "sqlite.sql"
    assert schema_path("postgresql").name == "postgresql.sql"
    assert schema_path("mysql").name == "mysql.sql"
    assert schema_path("mariadb").name == "mariadb.sql"


def test_loads_complete_schema_files():
    for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
        baseline = load_schema_baseline(backend)
        assert baseline.name == BASELINE_NAME
        assert baseline.backend == backend
        assert baseline.sql.strip()
        assert len(baseline.checksum) == 64
        assert baseline.path.is_file()


def test_baseline_marker_is_not_migration_ledger():
    for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
        ddl = baseline_marker_sql(backend).lower()
        assert "schema_baseline" in ddl
        assert "schema_migrations" not in ddl
        assert "version integer primary key" not in ddl


def test_invalid_backend_is_rejected():
    try:
        normalize_backend_name("oracle")
    except ValueError as exc:
        assert "unsupported database backend" in str(exc)
    else:
        raise AssertionError("invalid backend should fail")
