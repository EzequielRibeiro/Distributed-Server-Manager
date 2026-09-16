#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


engine = "database/baseline_upgrade_engine.py"
replace_once(
    engine,
    "from content_bundle_schema import content_bundle_ddl\nfrom server_update_schema import server_update_ddl\n",
    "from content_bundle_schema import content_bundle_ddl\nfrom maintenance_schema import maintenance_ddl\nfrom server_update_schema import content_update_ddl, server_update_ddl\n",
)
replace_once(
    engine,
    '''SERVER_UPDATE_TABLES = {\n    "instance_update_policy",\n    "instance_update_state",\n    "instance_update_runs",\n}\n\n''',
    '''SERVER_UPDATE_TABLES = {\n    "instance_update_policy",\n    "instance_update_state",\n    "instance_update_runs",\n}\n\nCONTENT_UPDATE_TABLES = {\n    "content_update_policy",\n    "content_update_state",\n}\n\nMAINTENANCE_TABLES = {\n    "instance_maintenance_policy",\n    "instance_maintenance_state",\n    "instance_maintenance_runs",\n}\n\n''',
)
replace_once(
    engine,
    '''    _execute_script(backend, connection, server_update_ddl(backend.name))\n\n\ndef _upgrade_backup_job_retry_identity''',
    '''    _execute_script(backend, connection, server_update_ddl(backend.name))\n\n\ndef _upgrade_content_update_schema(backend: Any, connection: Any) -> None:\n    tables = _table_names(backend, connection)\n    present = CONTENT_UPDATE_TABLES & tables\n    if present == CONTENT_UPDATE_TABLES:\n        return\n    if present:\n        missing = sorted(CONTENT_UPDATE_TABLES - present)\n        raise DatabaseMigrationError(\n            "partial universal content update baseline upgrade; missing tables: "\n            + ", ".join(missing)\n        )\n    _execute_script(backend, connection, content_update_ddl(backend.name))\n    missing = sorted(CONTENT_UPDATE_TABLES - _table_names(backend, connection))\n    if missing:\n        raise DatabaseMigrationError(\n            "universal content update baseline upgrade incomplete; missing tables: "\n            + ", ".join(missing)\n        )\n\n\ndef _upgrade_maintenance_schema(backend: Any, connection: Any) -> None:\n    tables = _table_names(backend, connection)\n    present = MAINTENANCE_TABLES & tables\n    if present == MAINTENANCE_TABLES:\n        return\n    if present:\n        missing = sorted(MAINTENANCE_TABLES - present)\n        raise DatabaseMigrationError(\n            "partial maintenance baseline upgrade; missing tables: "\n            + ", ".join(missing)\n        )\n    _execute_script(backend, connection, maintenance_ddl(backend.name))\n    missing = sorted(MAINTENANCE_TABLES - _table_names(backend, connection))\n    if missing:\n        raise DatabaseMigrationError(\n            "maintenance baseline upgrade incomplete; missing tables: "\n            + ", ".join(missing)\n        )\n\n\ndef _upgrade_backup_job_retry_identity''',
)
replace_once(
    engine,
    '''    BaselineUpgrade(10, "universal_content_bundles", _upgrade_content_bundle_schema),\n    BaselineUpgrade(11, "datacenter_geography_metadata", _upgrade_datacenter_geography),\n)''',
    '''    BaselineUpgrade(10, "universal_content_bundles", _upgrade_content_bundle_schema),\n    BaselineUpgrade(11, "datacenter_geography_metadata", _upgrade_datacenter_geography),\n    BaselineUpgrade(12, "universal_content_update", _upgrade_content_update_schema),\n    BaselineUpgrade(13, "maintenance_restart_framework", _upgrade_maintenance_schema),\n)''',
)

build = Path("release/build_release.sh")
text = build.read_text(encoding="utf-8")
start_marker = '"${PYTHON_BIN}" - "${PACKAGE_ROOT}/update-manager/process-guard.sh" <<\'PY\'\n'
end_marker = 'for relative_path in \\\n'
start = text.index(start_marker)
end = text.index(end_marker, start)
verification = r'''bash -n "${PACKAGE_ROOT}/update-manager/process-guard.sh" || fail "packaged process-guard.sh failed syntax validation"
if grep -q 'fully reconciled ledger is already compatible' "${PACKAGE_ROOT}/update-manager/process-guard.sh"
then
    fail "packaged process-guard.sh contains unsafe checksum-mismatch bypass"
fi

readarray -t BASELINE_GUARD_PAYLOADS < <(PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" - "${PACKAGE_ROOT}" <<'PAYLOADPY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "database"))
from baseline_upgrade_engine import UPGRADES, latest_upgrade_version

latest = latest_upgrade_version()
if latest < 13:
    raise SystemExit("release baseline upgrade ledger must include versions 12 and 13")

def payload(current_version, pending, checksum_matches=False):
    return json.dumps({
        "schema_version": 2,
        "kind": "DatabaseCheck",
        "driver": "postgresql",
        "connected": True,
        "initialized": True,
        "health": "error",
        "baseline": "capivara-baseline-v2",
        "baseline_checksum": "historical-ledger-checksum",
        "expected_baseline": "capivara-baseline-v2",
        "expected_checksum": "target-release-checksum",
        "checksum_matches": checksum_matches,
        "missing_tables": [],
        "upgrade_ledger": True,
        "upgrade_version": current_version,
        "upgrade_latest": latest,
        "pending_upgrades": pending,
        "upgrade_error": None,
        "valid": False,
    }, separators=(",", ":"))

pending = [
    {"version": upgrade.version, "name": upgrade.name}
    for upgrade in UPGRADES
    if upgrade.version > 11
]
print(payload(11, pending))
print(payload(latest, []))
PAYLOADPY
)

(( ${#BASELINE_GUARD_PAYLOADS[@]} == 2 )) || fail "failed to build packaged Baseline v2 guard payloads"
PENDING_PAYLOAD="${BASELINE_GUARD_PAYLOADS[0]}"
STALE_PAYLOAD="${BASELINE_GUARD_PAYLOADS[1]}"

if ! PYTHONDONTWRITEBYTECODE=1 PAYLOAD="${PENDING_PAYLOAD}" TARGET_ROOT="${PACKAGE_ROOT}" bash -c 'source "$TARGET_ROOT/update-manager/process-guard.sh"; process_guard_database_check_is_upgradeable "$PAYLOAD" "$TARGET_ROOT"'
then
    fail "packaged Baseline v2 guard rejected registered v12/v13 pending upgrades"
fi

if PYTHONDONTWRITEBYTECODE=1 PAYLOAD="${STALE_PAYLOAD}" TARGET_ROOT="${PACKAGE_ROOT}" bash -c 'source "$TARGET_ROOT/update-manager/process-guard.sh"; process_guard_database_check_is_upgradeable "$PAYLOAD" "$TARGET_ROOT"'
then
    fail "packaged Baseline v2 guard accepted checksum mismatch without pending upgrade"
fi

'''
text = text[:start] + verification + text[end:]
build.write_text(text, encoding="utf-8", newline="\n")


test_path = "tests/update_baseline_upgrade_path_test.py"
replace_once(
    test_path,
    '''    def test_migrate_advances_v10_datacenter_geography_to_v11(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp) / "dsm"\n            database = root / "data" / "capivara.db"\n            database.parent.mkdir(parents=True)\n\n            initialized = self.manager(root, database, "init")\n            self.assertEqual(initialized.returncode, 0, initialized.stderr)\n\n            with sqlite3.connect(database) as connection:\n                connection.execute("DELETE FROM baseline_upgrades WHERE version=11")\n                for column in ("state_name", "state_code", "country_name"):\n                    connection.execute(f"ALTER TABLE datacenters DROP COLUMN {column}")\n                connection.execute(\n                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",\n                    ("v10-checksum-simulation",),\n                )\n                connection.commit()\n\n            migrated = self.manager(root, database, "migrate")\n            self.assertEqual(migrated.returncode, 0, migrated.stderr)\n            payload = json.loads(migrated.stdout)\n            self.assertEqual(payload["upgrade_version"], 11)\n            self.assertEqual(payload["upgrade_latest"], 11)\n            self.assertTrue(payload["valid"])\n\n            with sqlite3.connect(database) as connection:\n                columns = {\n                    row[1] for row in connection.execute("PRAGMA table_info('datacenters')")\n                }\n                ledger = connection.execute(\n                    "SELECT version,name FROM baseline_upgrades WHERE version=11"\n                ).fetchone()\n\n            self.assertTrue({"country_name", "state_code", "state_name"} <= columns)\n            self.assertEqual(ledger, (11, "datacenter_geography_metadata"))\n\n''',
    '''    def test_migrate_advances_v10_through_current_baseline(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp) / "dsm"\n            database = root / "data" / "capivara.db"\n            database.parent.mkdir(parents=True)\n\n            initialized = self.manager(root, database, "init")\n            self.assertEqual(initialized.returncode, 0, initialized.stderr)\n\n            with sqlite3.connect(database) as connection:\n                connection.execute("DELETE FROM baseline_upgrades WHERE version>=11")\n                for table in (\n                    "instance_maintenance_runs",\n                    "instance_maintenance_state",\n                    "instance_maintenance_policy",\n                    "content_update_state",\n                    "content_update_policy",\n                ):\n                    connection.execute(f"DROP TABLE {table}")\n                for column in ("state_name", "state_code", "country_name"):\n                    connection.execute(f"ALTER TABLE datacenters DROP COLUMN {column}")\n                connection.execute(\n                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",\n                    ("v10-checksum-simulation",),\n                )\n                connection.commit()\n\n            migrated = self.manager(root, database, "migrate")\n            self.assertEqual(migrated.returncode, 0, migrated.stderr)\n            payload = json.loads(migrated.stdout)\n            self.assertEqual(payload["upgrade_version"], latest_upgrade_version())\n            self.assertEqual(payload["upgrade_latest"], latest_upgrade_version())\n            self.assertTrue(payload["valid"])\n\n            with sqlite3.connect(database) as connection:\n                columns = {\n                    row[1] for row in connection.execute("PRAGMA table_info('datacenters')")\n                }\n                ledger = connection.execute(\n                    "SELECT version,name FROM baseline_upgrades WHERE version>=11 ORDER BY version"\n                ).fetchall()\n\n            self.assertTrue({"country_name", "state_code", "state_name"} <= columns)\n            self.assertEqual(\n                ledger,\n                [\n                    (11, "datacenter_geography_metadata"),\n                    (12, "universal_content_update"),\n                    (13, "maintenance_restart_framework"),\n                ],\n            )\n\n    def test_migrate_2062_v11_database_through_content_and_maintenance(self) -> None:\n        old_2062_checksum = "b8d7de4a314faf5086bf02bcbc626dbbef94ba1a84eb2490f068cbb74c7634ce"\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp) / "dsm"\n            database = root / "data" / "capivara.db"\n            database.parent.mkdir(parents=True)\n\n            initialized = self.manager(root, database, "init")\n            self.assertEqual(initialized.returncode, 0, initialized.stderr)\n\n            with sqlite3.connect(database) as connection:\n                connection.execute("DELETE FROM baseline_upgrades WHERE version>=12")\n                for table in (\n                    "instance_maintenance_runs",\n                    "instance_maintenance_state",\n                    "instance_maintenance_policy",\n                    "content_update_state",\n                    "content_update_policy",\n                ):\n                    connection.execute(f"DROP TABLE {table}")\n                connection.execute(\n                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",\n                    (old_2062_checksum,),\n                )\n                connection.commit()\n\n            before = self.manager(root, database, "check")\n            self.assertEqual(before.returncode, 1, before.stderr)\n            before_payload = json.loads(before.stdout)\n            self.assertEqual(before_payload["upgrade_version"], 11)\n            self.assertEqual(before_payload["upgrade_latest"], 13)\n            self.assertEqual(\n                before_payload["pending_upgrades"],\n                [\n                    {"version": 12, "name": "universal_content_update"},\n                    {"version": 13, "name": "maintenance_restart_framework"},\n                ],\n            )\n            self.assertEqual(self.guard_classifier(before_payload).returncode, 0)\n\n            migrated = self.manager(root, database, "migrate")\n            self.assertEqual(migrated.returncode, 0, migrated.stderr)\n            migrated_payload = json.loads(migrated.stdout)\n            self.assertTrue(migrated_payload["valid"])\n            self.assertEqual(migrated_payload["upgrade_version"], 13)\n            self.assertEqual(migrated_payload["upgrade_latest"], 13)\n\n            with sqlite3.connect(database) as connection:\n                tables = {\n                    row[0]\n                    for row in connection.execute(\n                        "SELECT name FROM sqlite_master WHERE type='table'"\n                    ).fetchall()\n                }\n                indexes = {\n                    row[0]\n                    for row in connection.execute(\n                        "SELECT name FROM sqlite_master WHERE type='index'"\n                    ).fetchall()\n                }\n                ledger = connection.execute(\n                    "SELECT version,name FROM baseline_upgrades WHERE version>=12 ORDER BY version"\n                ).fetchall()\n\n            self.assertTrue(\n                {\n                    "content_update_policy",\n                    "content_update_state",\n                    "instance_maintenance_policy",\n                    "instance_maintenance_state",\n                    "instance_maintenance_runs",\n                } <= tables\n            )\n            self.assertTrue(\n                {\n                    "idx_content_update_state_instance",\n                    "idx_content_update_state_agent",\n                    "idx_instance_maintenance_state_due",\n                    "idx_instance_maintenance_runs_instance",\n                } <= indexes\n            )\n            self.assertEqual(\n                ledger,\n                [\n                    (12, "universal_content_update"),\n                    (13, "maintenance_restart_framework"),\n                ],\n            )\n\n    def test_migrate_2063_v11_existing_content_schema_is_idempotent(self) -> None:\n        old_2063_checksum = "c328a768093c98600742ccf73ef01832a99190e3eee0f28e707b0f59a8a63189"\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp) / "dsm"\n            database = root / "data" / "capivara.db"\n            database.parent.mkdir(parents=True)\n\n            initialized = self.manager(root, database, "init")\n            self.assertEqual(initialized.returncode, 0, initialized.stderr)\n\n            with sqlite3.connect(database) as connection:\n                connection.execute("DELETE FROM baseline_upgrades WHERE version>=12")\n                for table in (\n                    "instance_maintenance_runs",\n                    "instance_maintenance_state",\n                    "instance_maintenance_policy",\n                ):\n                    connection.execute(f"DROP TABLE {table}")\n                connection.execute(\n                    "UPDATE schema_baseline SET checksum=? WHERE singleton=1",\n                    (old_2063_checksum,),\n                )\n                connection.commit()\n\n            migrated = self.manager(root, database, "migrate")\n            self.assertEqual(migrated.returncode, 0, migrated.stderr)\n            payload = json.loads(migrated.stdout)\n            self.assertTrue(payload["valid"])\n            self.assertEqual(payload["upgrade_version"], 13)\n\n            with sqlite3.connect(database) as connection:\n                ledger = connection.execute(\n                    "SELECT version,name FROM baseline_upgrades WHERE version>=12 ORDER BY version"\n                ).fetchall()\n            self.assertEqual(\n                ledger,\n                [\n                    (12, "universal_content_update"),\n                    (13, "maintenance_restart_framework"),\n                ],\n            )\n\n''',
)
replace_once(
    test_path,
    '''    def test_process_guard_rejects_unknown_preledger_checksum(self) -> None:\n''',
    '''    def test_process_guard_rejects_checksum_mismatch_without_pending_upgrade(self) -> None:\n        payload = {\n            "schema_version": 2,\n            "kind": "DatabaseCheck",\n            "driver": "postgresql",\n            "connected": True,\n            "initialized": True,\n            "health": "error",\n            "baseline": "capivara-baseline-v2",\n            "baseline_checksum": "historical",\n            "expected_baseline": "capivara-baseline-v2",\n            "expected_checksum": "current",\n            "checksum_matches": False,\n            "missing_tables": [],\n            "upgrade_ledger": True,\n            "upgrade_version": latest_upgrade_version(),\n            "upgrade_latest": latest_upgrade_version(),\n            "pending_upgrades": [],\n            "upgrade_error": None,\n            "valid": False,\n        }\n        result = self.guard_classifier(payload)\n        self.assertNotEqual(result.returncode, 0)\n\n    def test_process_guard_rejects_unknown_preledger_checksum(self) -> None:\n''',
)
