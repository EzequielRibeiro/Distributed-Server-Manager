#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one anchor in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


engine = "database/baseline_upgrade_engine.py"
replace_once(
    engine,
    "from server_update_schema import server_update_ddl\n",
    "from server_update_schema import content_update_ddl, server_update_ddl\n",
)
replace_once(
    engine,
    '''SERVER_UPDATE_TABLES = {\n    "instance_update_policy",\n    "instance_update_state",\n    "instance_update_runs",\n}\n\n''',
    '''SERVER_UPDATE_TABLES = {\n    "instance_update_policy",\n    "instance_update_state",\n    "instance_update_runs",\n}\n\nCONTENT_UPDATE_TABLES = {\n    "content_update_policy",\n    "content_update_state",\n}\n\n''',
)
replace_once(
    engine,
    '''    _execute_script(backend, connection, server_update_ddl(backend.name))\n\n\ndef _upgrade_backup_job_retry_identity''',
    '''    _execute_script(backend, connection, server_update_ddl(backend.name))\n\n\ndef _upgrade_content_update_schema(backend: Any, connection: Any) -> None:\n    tables = _table_names(backend, connection)\n    present = CONTENT_UPDATE_TABLES & tables\n    if present == CONTENT_UPDATE_TABLES:\n        return\n    if present:\n        missing = sorted(CONTENT_UPDATE_TABLES - present)\n        raise DatabaseMigrationError(\n            "partial universal content update baseline upgrade; missing tables: "\n            + ", ".join(missing)\n        )\n    _execute_script(backend, connection, content_update_ddl(backend.name))\n    missing = sorted(CONTENT_UPDATE_TABLES - _table_names(backend, connection))\n    if missing:\n        raise DatabaseMigrationError(\n            "universal content update baseline upgrade incomplete; missing tables: "\n            + ", ".join(missing)\n        )\n\n\ndef _upgrade_backup_job_retry_identity''',
)
replace_once(
    engine,
    '''    BaselineUpgrade(11, "datacenter_geography_metadata", _upgrade_datacenter_geography),\n)''',
    '''    BaselineUpgrade(11, "datacenter_geography_metadata", _upgrade_datacenter_geography),\n    BaselineUpgrade(12, "universal_content_update", _upgrade_content_update_schema),\n)''',
)

build = Path("release/build_release.sh")
text = build.read_text(encoding="utf-8")
start = text.index('"${PYTHON_BIN}" - "${PACKAGE_ROOT}/update-manager/process-guard.sh" <<\'PY\'\n')
end = text.index('for relative_path in \\\n', start)
text = text[:start] + text[end:]
build.write_text(text, encoding="utf-8", newline="\n")

Path("tests/baseline_v12_content_update_test.py").write_text(r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
MANAGER = DATABASE / "manager.py"
GUARD = ROOT / "update-manager" / "process-guard.sh"
OLD_2062_CHECKSUM = "b8d7de4a314faf5086bf02bcbc626dbbef94ba1a84eb2490f068cbb74c7634ce"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))
from baseline_upgrade_engine import latest_upgrade_version


class BaselineV12ContentUpdateTest(unittest.TestCase):
    def manager(self, root: Path, db: Path, command: str):
        return subprocess.run(
            [sys.executable, str(MANAGER), "--root", str(root), "--driver", "sqlite", "--database", str(db), command],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

    def v11_database(self, root: Path, db: Path) -> None:
        initialized = self.manager(root, db, "init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        with sqlite3.connect(db) as connection:
            connection.execute("DELETE FROM baseline_upgrades WHERE version=12")
            connection.execute("DROP TABLE content_update_state")
            connection.execute("DROP TABLE content_update_policy")
            connection.execute("UPDATE schema_baseline SET checksum=? WHERE singleton=1", (OLD_2062_CHECKSUM,))
            connection.commit()

    def test_2062_v11_database_advances_to_v12(self) -> None:
        self.assertEqual(latest_upgrade_version(), 12)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsm"
            db = root / "data" / "capivara.db"
            db.parent.mkdir(parents=True)
            self.v11_database(root, db)
            before = self.manager(root, db, "check")
            self.assertEqual(before.returncode, 1, before.stderr)
            payload = json.loads(before.stdout)
            self.assertEqual(payload["upgrade_version"], 11)
            self.assertEqual(payload["upgrade_latest"], 12)
            self.assertEqual(payload["pending_upgrades"], [{"version": 12, "name": "universal_content_update"}])

            migrated = self.manager(root, db, "migrate")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            payload = json.loads(migrated.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["upgrade_version"], 12)
            self.assertEqual(payload["upgrade_latest"], 12)

            with sqlite3.connect(db) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertTrue({"content_update_policy", "content_update_state"} <= tables)
            self.assertTrue({"idx_content_update_state_instance", "idx_content_update_state_agent"} <= indexes)

    def test_guard_rejects_checksum_mismatch_without_pending_upgrade(self) -> None:
        payload = {
            "schema_version": 2, "kind": "DatabaseCheck", "driver": "postgresql",
            "connected": True, "initialized": True, "health": "error",
            "baseline": "capivara-baseline-v2", "baseline_checksum": OLD_2062_CHECKSUM,
            "expected_baseline": "capivara-baseline-v2", "expected_checksum": "target-checksum",
            "checksum_matches": False, "missing_tables": [], "upgrade_ledger": True,
            "upgrade_version": 11, "upgrade_latest": 11, "pending_upgrades": [],
            "upgrade_error": None, "valid": False,
        }
        script = f'source "{GUARD}"; process_guard_database_check_is_upgradeable "$PAYLOAD" "{ROOT}"'
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env={**__import__("os").environ, "PAYLOAD": json.dumps(payload)}, text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_release_builder_does_not_weaken_process_guard(self) -> None:
        text = (ROOT / "release" / "build_release.sh").read_text(encoding="utf-8")
        self.assertNotIn("fully reconciled ledger is already compatible", text)
        self.assertNotIn("Baseline v2 preflight hotfix anchor", text)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8", newline="\n")

replace_once(
    ".github/workflows/baseline-update-reconciliation.yml",
    "          python3 -m unittest tests/update_baseline_upgrade_path_test.py\n",
    "          python3 -m unittest tests/update_baseline_upgrade_path_test.py\n          python3 -m unittest tests/baseline_v12_content_update_test.py\n",
)
replace_once(
    ".github/workflows/release.yml",
    "          python3 -m unittest tests/update_baseline_upgrade_path_test.py\n",
    "          python3 -m unittest tests/update_baseline_upgrade_path_test.py\n          python3 -m unittest tests/baseline_v12_content_update_test.py\n",
)
