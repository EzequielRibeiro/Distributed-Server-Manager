#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path: sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from observability_http import dispatch_observability_get
from observability_repository import ObservabilityRepository


class ObservabilityHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-controller", "Controller", "controller"))
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-agent", "Agent", "agent"))
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)", ("controller-c3", "node-controller", "C3"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-c3", "controller-c3", "node-agent", "Agent", "active"))
        repo = ObservabilityRepository(self.backend); repo.initialize()
        repo.ingest_agent_samples("agent-c3", [{"metric_name": "system.load.1", "value": 0.25, "unit": "load"}])

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    def test_admin_can_query_latest_history_and_summary(self):
        admin = {"role": "admin", "id": "admin-c3"}
        for mode in ("latest", "history", "summary"):
            status, body = dispatch_observability_get("/api/observability", f"mode={mode}&agent_id=agent-c3", user=admin, backend=self.backend)
            self.assertEqual(status, 200)
            self.assertEqual(body["count"], 1)

    def test_non_admin_is_forbidden(self):
        status, body = dispatch_observability_get("/api/observability", "", user={"role": "customer"}, backend=self.backend)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")


if __name__ == "__main__": unittest.main()
