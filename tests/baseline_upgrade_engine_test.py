#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from backend import DatabaseMigrationError
from baseline_upgrade_engine import (
    LEGACY_BASELINE_START_VERSION,
    apply_pending_upgrades,
    seed_current_upgrades,
    upgrade_status,
    latest_upgrade_version,
)


class SQLiteBackend:
    name = "sqlite"


class BaselineUpgradeEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = SQLiteBackend()
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        # The baseline engine now has 22 registered upgrades. Use the
        # consolidated schema instead of an obsolete two-table v2 fixture;
        # later upgrades require alert_events and other core tables.
        self.connection.executescript(
            (ROOT / "database" / "schemas" / "sqlite.sql").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self.connection.close()

    def versions(self) -> list[int]:
        return [
            int(row[0])
            for row in self.connection.execute(
                "SELECT version FROM baseline_upgrades ORDER BY version"
            ).fetchall()
        ]

    def test_fresh_current_baseline_seeds_all_upgrade_versions(self) -> None:
        seed_current_upgrades(self.backend, self.connection)
        self.assertEqual(self.versions(), list(range(1, latest_upgrade_version() + 1)))
        status = upgrade_status(self.backend, self.connection)
        self.assertEqual(status["current_version"], latest_upgrade_version())
        self.assertEqual(status["pending"], [])

    def test_pre_ledger_legacy_baseline_is_upgraded_once(self) -> None:
        checksum = next(iter(LEGACY_BASELINE_START_VERSION))
        completed = apply_pending_upgrades(
            self.backend,
            self.connection,
            installed_checksum=checksum,
        )
        self.assertEqual(completed, list(range(1, latest_upgrade_version() + 1)))
        self.assertEqual(self.versions(), list(range(1, latest_upgrade_version() + 1)))
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("customer_discord_connections", tables)
        self.assertIn("agent_public_network_preconfiguration", tables)

    def test_existing_ledger_allows_future_progress_without_checksum_map(self) -> None:
        seed_current_upgrades(self.backend, self.connection)
        # Keep the historical ledger contiguous; do not leave versions 3..22
        # behind while testing an upgrade starting at version 2.
        self.connection.execute("DELETE FROM baseline_upgrades WHERE version >= 2")
        self.connection.execute("DROP TABLE IF EXISTS agent_public_network_preconfiguration")
        completed = apply_pending_upgrades(
            self.backend,
            self.connection,
            installed_checksum="future-release-checksum-not-in-legacy-map",
        )
        self.assertEqual(completed, list(range(2, latest_upgrade_version() + 1)))
        self.assertEqual(self.versions(), list(range(1, latest_upgrade_version() + 1)))

    def test_unknown_pre_ledger_checksum_is_rejected(self) -> None:
        with self.assertRaises(DatabaseMigrationError):
            apply_pending_upgrades(
                self.backend,
                self.connection,
                installed_checksum="unknown-pre-ledger-checksum",
            )


if __name__ == "__main__":
    unittest.main()
