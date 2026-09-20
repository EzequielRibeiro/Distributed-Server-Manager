#!/usr/bin/env python3
"""Destructive Baseline v2 gate for isolated MySQL and MariaDB services."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baseline_upgrade_engine import UPGRADES, apply_pending_upgrades
from runtime_backend import backend_from_environment
from schema_parity import assert_customer_schema_parity


def require_isolated_target() -> str:
    if os.environ.get("CAPIVARA_ALLOW_ISOLATED_DB_TEST") != "1":
        raise RuntimeError("isolated database test requires CAPIVARA_ALLOW_ISOLATED_DB_TEST=1")
    configured = os.environ.get("DSM_DATABASE_DRIVER", "").strip().lower()
    if configured not in {"mysql", "mariadb"}:
        raise RuntimeError("isolated deployment gate requires MySQL or MariaDB")
    expected = os.environ.get("CAPIVARA_EXPECTED_DB_FLAVOR", "").strip().lower()
    if expected not in {"mysql", "mariadb"}:
        raise RuntimeError("CAPIVARA_EXPECTED_DB_FLAVOR must be mysql or mariadb")
    name = os.environ.get("DSM_DATABASE_NAME", "").strip().lower()
    if not name or "test" not in name:
        raise RuntimeError("DSM_DATABASE_NAME must contain 'test' for destructive isolated bootstrap")
    return expected


def rows(cursor, sql, params=None):
    cursor.execute(sql, params or ())
    return cursor.fetchall()


def row_value(row, key):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        expected = key.lower()
        for candidate in row.keys():
            if str(candidate).lower() == expected:
                return row[candidate]
    raise KeyError(key)


def main() -> int:
    expected_flavor = require_isolated_target()
    assert_customer_schema_parity(ROOT / "database")

    backend = backend_from_environment()
    if backend.name != "mysql":
        raise AssertionError(f"unexpected normalized backend: {backend.name}")

    status = backend.initialize()
    if status["health"] != "ok" or status["upgrade_version"] != len(UPGRADES):
        raise AssertionError(f"unexpected baseline status: {status}")

    with backend.connect() as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            server = rows(cursor, "SELECT VERSION() AS version")[0]
            version_text = str(server["version"]).lower()
            detected = "mariadb" if "mariadb" in version_text else "mysql"
            if detected != expected_flavor:
                raise AssertionError(
                    f"expected {expected_flavor} service, got {server['version']}"
                )

            ledger = rows(
                cursor,
                "SELECT version,name FROM baseline_upgrades ORDER BY version",
            )
            expected_ledger = [(u.version, u.name) for u in UPGRADES]
            actual_ledger = [(int(r["version"]), str(r["name"])) for r in ledger]
            if actual_ledger != expected_ledger:
                raise AssertionError(
                    f"upgrade ledger mismatch: expected {expected_ledger}, got {actual_ledger}"
                )

            tables = {
                str(row_value(r, "table_name"))
                for r in rows(
                    cursor,
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=DATABASE()",
                )
            }
            required = {
                "customers",
                "dashboard_users",
                "service_contracts",
                "instances",
                "activity_audit",
                "universal_events",
                "alerts",
                "alert_events",
                "instance_update_policy",
                "content_bundles",
                "instance_maintenance_policy",
                "yarax_admin_operations",
                "native_restart_commands",
                "baseline_upgrades",
                "database_metrics_daily",
            }
            missing = sorted(required - tables)
            if missing:
                raise AssertionError("Baseline v2 missing tables: " + ", ".join(missing))

            columns = {
                str(row_value(r, "column_name"))
                for r in rows(
                    cursor,
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=DATABASE() AND table_name='datacenters'",
                )
            }
            for column in {"country_name", "state_code", "state_name"}:
                if column not in columns:
                    raise AssertionError(f"datacenters.{column} is missing")

            if expected_flavor == "mysql":
                fk_rows = rows(
                    cursor,
                    "SELECT TABLE_NAME AS child_table, CONSTRAINT_NAME AS constraint_name, "
                    "REFERENCED_TABLE_NAME AS parent_table, "
                    "GROUP_CONCAT(REFERENCED_COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR ',') AS parent_columns "
                    "FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE CONSTRAINT_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL "
                    "GROUP BY TABLE_NAME,CONSTRAINT_NAME,REFERENCED_TABLE_NAME",
                )
                nonstandard = []
                for fk in fk_rows:
                    parent = str(row_value(fk, "parent_table"))
                    parent_columns = str(row_value(fk, "parent_columns"))
                    unique_indexes = rows(
                        cursor,
                        "SELECT INDEX_NAME AS index_name, "
                        "GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') AS columns_csv "
                        "FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND NON_UNIQUE=0 "
                        "GROUP BY INDEX_NAME",
                        (parent,),
                    )
                    if not any(str(row_value(idx, "columns_csv")) == parent_columns for idx in unique_indexes):
                        nonstandard.append(
                            f"{row_value(fk, 'child_table')}.{row_value(fk, 'constraint_name')} -> "
                            f"{parent}({parent_columns})"
                        )
                if nonstandard:
                    raise AssertionError(
                        "MySQL nonstandard foreign keys: " + "; ".join(nonstandard)
                    )

            indexes = rows(
                cursor,
                "SELECT INDEX_NAME AS index_name, NON_UNIQUE AS non_unique, "
                "GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX SEPARATOR ',') AS columns_csv "
                "FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='backup_jobs' "
                "GROUP BY INDEX_NAME, NON_UNIQUE",
            )
            backup_id_indexes = [
                r for r in indexes
                if str(row_value(r, "columns_csv") or "") == "backup_id"
            ]
            if any(int(row_value(r, "non_unique") or 0) == 0 for r in backup_id_indexes):
                raise AssertionError("backup_jobs.backup_id remains unique")
            if not any(
                str(row_value(r, "index_name") or "") == "idx_backup_jobs_backup_id"
                and int(r.get("non_unique") or 0) == 1
                for r in backup_id_indexes
            ):
                raise AssertionError("backup_jobs backup_id lookup index is missing")

            # Prove that the latest registered post-baseline upgrade can be replayed
            # against the real server flavor. Remove v19 and its Customer identity
            # column, then let the upgrade engine restore it without a ledger gap.
            cursor.execute("DELETE FROM baseline_upgrades WHERE version=%s", (19,))
            cursor.execute("ALTER TABLE alerts DROP COLUMN customer_id")
            connection.commit()

            marker = rows(cursor, "SELECT checksum FROM schema_baseline LIMIT 1")[0]
            completed = apply_pending_upgrades(
                backend,
                connection,
                installed_checksum=str(marker["checksum"]),
            )
            connection.commit()
            if completed != [19]:
                raise AssertionError(f"expected replay of upgrade 19, got {completed}")

            restored = rows(
                cursor,
                "SELECT COUNT(*) AS total FROM information_schema.columns "
                "WHERE table_schema=DATABASE() AND table_name='alerts' "
                "AND column_name='customer_id'",
            )[0]
            if int(row_value(restored, "total")) != 1:
                raise AssertionError("Customer alert identity upgrade did not restore its column")

            restored_ledger = rows(
                cursor,
                "SELECT version,name FROM baseline_upgrades ORDER BY version",
            )
            if [(int(r["version"]), str(r["name"])) for r in restored_ledger] != expected_ledger:
                raise AssertionError("upgrade ledger was not restored after replay")
        finally:
            cursor.close()

    health = backend.health_check()
    if not health["valid"] or health["health"] != "ok":
        raise AssertionError(f"final database health failed: {health}")

    print(f"{expected_flavor.upper()} Baseline v2 isolated deployment: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
