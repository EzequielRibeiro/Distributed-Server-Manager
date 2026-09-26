#!/usr/bin/env python3
"""Regression: database ownership checks need both node and game identity."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database"):
    sys.path.insert(0, str(path))

from dashboard_repository import DashboardRepository
import server


class RegisteredInstanceIdentityTest(unittest.TestCase):
    def test_real_repository_context_exposes_game_for_failed_instance(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript("""
                CREATE TABLE instances (
                  id TEXT, node_id TEXT, game_id TEXT, customer_id INTEGER,
                  controller_id TEXT, agent_id TEXT
                );
                INSERT INTO instances VALUES (
                  'cli-000001-minecraft-001','horizon-server','minecraft',
                  1,'controller-horizon-server','agent-horizon-server'
                );
            """)
            repo = object.__new__(DashboardRepository)
            repo.dialect = type("Dialect", (), {"placeholder": "?"})()
            repo.session = lambda: connection
            record = repo.instance_context("cli-000001-minecraft-001")
            self.assertEqual(record["game_id"], "minecraft")

            with tempfile.TemporaryDirectory() as directory:
                instances = Path(directory) / "instances"
                missing = instances / "horizon-server" / "minecraft" / "cli-000001-minecraft-001"
                with patch.object(server, "INSTANCE_ROOT", instances), \
                     patch.object(server, "dashboard_repository", return_value=repo):
                    self.assertTrue(server.can_access_instance(
                        {"role": "customer", "scope_id": 1}, missing))
                    self.assertFalse(server.can_access_instance(
                        {"role": "customer", "scope_id": 2}, missing))
                    self.assertFalse(server.can_access_instance(
                        {"role": "customer", "scope_id": 1},
                        instances / "horizon-server" / "dayz" / "cli-000001-minecraft-001"))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
