#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard" / "workers"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from observability_repository import ObservabilityRepository
from observability_retention_worker import ObservabilityRetentionWorker


class ObservabilityRetentionWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("node-controller", "Controller", "controller"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                ("node-agent", "Agent", "agent"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",
                ("controller-c3", "node-controller", "C3"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-c3", "controller-c3", "node-agent", "Agent C3", "active"),
            )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_worker_prunes_in_bounded_batches(self):
        repo = ObservabilityRepository(self.backend, history_interval_seconds=60)
        for minute in range(6):
            repo.ingest_agent_samples(
                "agent-c3",
                [{
                    "metric_name": "system.load.1",
                    "value": float(minute),
                    "unit": "load",
                    "collected_at": f"2026-09-01T00:0{minute}:00Z",
                }],
            )
        worker = ObservabilityRetentionWorker(self.backend, retention_days=7, batch_size=100)
        report = worker.tick(datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertEqual(report["pending"], 6)
        self.assertEqual(report["deleted"], 6)
        self.assertEqual(repo.count_before("2026-09-13T00:00:00Z"), 0)


if __name__ == "__main__":
    unittest.main()
