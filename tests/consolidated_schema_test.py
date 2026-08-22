#!/usr/bin/env python3
"""Contract tests for clean-install consolidated schemas."""

from pathlib import Path
import re
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))
import sqlite_engine  # noqa: E402


class ConsolidatedSchemaTest(unittest.TestCase):
    def test_all_supported_backends_have_complete_schema(self):
        for backend in ("sqlite", "postgresql", "mysql", "mariadb"):
            schema = (ROOT / "database" / "schemas" / f"{backend}.sql").read_text()
            self.assertIn("CREATE TABLE agent_pairing_tokens", schema)
            self.assertIn("CREATE TABLE agent_credentials", schema)
            self.assertIn("CREATE TABLE agent_runtime_inventory", schema)
            self.assertLess(schema.index("CREATE TABLE agent_pairing_tokens"),
                            schema.index("ALTER TABLE agent_pairing_tokens ADD COLUMN platform"))
            for table in ("nodes", "instances", "controllers", "agents",
                          "regions", "datacenters", "dashboard_users"):
                self.assertRegex(
                    schema,
                    rf"CREATE TABLE(?: IF NOT EXISTS)?\s+{re.escape(table)}\b",
                )

    def test_sqlite_clean_install_is_one_baseline_and_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "capivara.db"
            first = sqlite_engine.initialize(database)
            second = sqlite_engine.initialize(database)
            self.assertEqual(first["applied_now"], [41])
            self.assertEqual(second["applied_now"], [])
            self.assertTrue(sqlite_engine.check_database(database)["valid"])
            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute(
                    "SELECT version,name FROM schema_migrations"
                ).fetchall()
            self.assertEqual(rows, [(41, "consolidated_schema")])

    def test_database_validation_precedes_capivara_persistence(self):
        installer = (ROOT / "install-core.sh").read_text(encoding="utf-8")
        main = installer[installer.index("main()") :]
        self.assertLess(main.index("prevalidate_database"),
                        main.index("ensure_service_account"))
        self.assertLess(main.index("prevalidate_database"),
                        main.index("install_project_files"))
        self.assertLess(main.index("initialize_database"),
                        main.index("install_systemd_units"))

    def test_network_preflight_validates_consolidated_schema(self):
        setup = (ROOT / "installer" / "database_setup.sh").read_text(encoding="utf-8")
        preflight = setup[setup.index("prevalidate_database()") :]
        self.assertLess(preflight.index("run_source_database_manager check"),
                        preflight.index("run_source_database_manager init"))
        self.assertIn("Schema do banco ausente, parcial ou incompatível", preflight)

    def test_secret_contract_is_automatic_and_never_prints_value(self):
        entrypoint = (ROOT / "install.sh").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "database_setup.sh").read_text(encoding="utf-8")
        self.assertIn("/etc/capivara/secrets/database-password", entrypoint)
        self.assertIn("read -r -s", entrypoint)
        self.assertIn("install -d -m 700", entrypoint)
        self.assertIn("chmod 600", entrypoint)
        self.assertNotIn("Arquivo protegido contendo a senha", entrypoint)
        self.assertIn("chown \"${DSM_SERVICE_USER}:${DSM_SERVICE_GROUP}\"", setup)

    def test_interactive_topology_has_review_and_confirmation(self):
        entrypoint = (ROOT / "install.sh").read_text(encoding="utf-8")
        topology = entrypoint[entrypoint.index("select_initial_topology()") :
                              entrypoint.index("bootstrap_initial_topology()")]
        self.assertIn("Revisão da topologia inicial", topology)
        self.assertIn("Os dados estão corretos? [S/n]", topology)
        self.assertIn("while true", topology)


if __name__ == "__main__":
    unittest.main()
