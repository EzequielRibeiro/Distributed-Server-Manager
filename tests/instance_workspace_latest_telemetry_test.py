#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from instance_workspace_repository import InstanceWorkspaceRepository


class InstanceWorkspaceLatestTelemetryTest(unittest.TestCase):
    def test_latest_telemetry_returns_only_newest_sample_per_instance(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "telemetry.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE instance_telemetry_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        instance_id TEXT NOT NULL,
                        cpu_percent DOUBLE PRECISION,
                        memory_bytes INTEGER,
                        storage_used_bytes INTEGER,
                        network_rx_bytes INTEGER,
                        network_tx_bytes INTEGER,
                        players_online INTEGER,
                        players_max INTEGER,
                        latency_ms DOUBLE PRECISION,
                        uptime_seconds INTEGER,
                        health TEXT,
                        sampled_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                connection.executemany(
                    "INSERT INTO instance_telemetry_samples("
                    "instance_id,cpu_percent,memory_bytes,players_online,players_max,health"
                    ") VALUES (?,?,?,?,?,?)",
                    (
                        ("dayz-1", 5.0, 100, 0, 32, "healthy"),
                        ("dayz-1", 7.5, 200, 1, 32, "healthy"),
                        ("minecraft-1", 3.0, 300, 4, 20, "healthy"),
                    ),
                )

            backend = create_backend(DatabaseConfig(driver="sqlite", database=str(database)))
            repository = InstanceWorkspaceRepository(backend)

            latest = repository.latest_telemetry(["dayz-1", "minecraft-1", "missing"])

            self.assertEqual(set(latest), {"dayz-1", "minecraft-1"})
            self.assertEqual(latest["dayz-1"]["players_online"], 1)
            self.assertEqual(latest["dayz-1"]["cpu_percent"], 7.5)
            self.assertEqual(latest["minecraft-1"]["players_online"], 4)


if __name__ == "__main__":
    unittest.main()
