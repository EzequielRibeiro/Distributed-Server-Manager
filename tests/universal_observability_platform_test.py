#!/usr/bin/env python3

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    if str(path) not in sys.path: sys.path.insert(0, str(path))

from agent_heartbeat_api import record_agent_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from observability_client import collect_observability
from observability_platform import ObservabilityValidationError, normalize_sample
from observability_repository import ObservabilityRepository


class ObservabilityContractTest(unittest.TestCase):
    def test_deterministic_sample_identity(self):
        raw = {"metric_name": "system.load.1", "agent_id": "agent-c3", "value": 0.5, "unit": "load", "collected_at": "2026-08-21T17:00:00Z"}
        one = normalize_sample(raw)
        two = normalize_sample(raw)
        self.assertEqual(one["sample_id"], two["sample_id"])
        self.assertEqual(one["kind"], "CapivaraMetricSample")

    def test_rejects_invalid_and_spoofed_samples(self):
        with self.assertRaises(ObservabilityValidationError):
            normalize_sample({"metric_name": "Bad Metric", "agent_id": "a", "value": 1})
        with self.assertRaises(ObservabilityValidationError):
            normalize_sample({"metric_name": "system.load", "agent_id": "other", "value": 1}, authenticated_agent_id="agent-c3")
        with self.assertRaises(ObservabilityValidationError):
            normalize_sample({"metric_name": "system.load", "agent_id": "agent-c3", "value": math.inf})

    def test_linux_collector_is_bounded_and_portable(self):
        rows = collect_observability({"agent_id": "agent-c3"})
        self.assertTrue(rows)
        self.assertLessEqual(len(rows), 2000)
        self.assertTrue(any(row["metric_name"].startswith("system.") or row["metric_name"].startswith("memory.") for row in rows))


class ObservabilityRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        with self.backend.transaction() as connection:
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-controller", "Controller", "controller"))
            connection.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)", ("node-agent", "Agent", "agent"))
            connection.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)", ("controller-c3", "node-controller", "C3"))
            connection.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)", ("agent-c3", "controller-c3", "node-agent", "Agent C3", "active"))
        self.repo = ObservabilityRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close(); self.temp.cleanup()

    def sample(self, value=1.0, at="2026-08-21T17:00:00Z"):
        return {"metric_name": "system.load.1", "metric_type": "gauge", "value": value, "unit": "load", "collected_at": at}

    def test_ingestion_is_idempotent_and_projects_latest(self):
        first = self.repo.ingest_agent_samples("agent-c3", [self.sample()])
        second = self.repo.ingest_agent_samples("agent-c3", [self.sample()])
        newer = self.repo.ingest_agent_samples("agent-c3", [self.sample(2.0, "2026-08-21T17:01:00Z")])
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(newer["created"], 1)
        latest = self.repo.latest(agent_id="agent-c3", metric_name="system.load.1")
        self.assertEqual(latest[0]["value"], 2.0)
        self.assertIsNone(latest[0]["instance_id"])

    def test_history_summary_and_instance_spoof_rejection(self):
        self.repo.ingest_agent_samples("agent-c3", [self.sample(1.0), self.sample(3.0, "2026-08-21T17:02:00Z")])
        history = self.repo.history(agent_id="agent-c3", metric_name="system.load.1")
        summary = self.repo.summary(agent_id="agent-c3", metric_name="system.load.1")
        self.assertEqual(len(history), 2)
        self.assertEqual(summary[0]["avg"], 2.0)
        bad = self.repo.ingest_agent_samples("agent-c3", [{"metric_name": "instance.health", "scope_type": "instance", "instance_id": "not-owned", "value": 1}])
        self.assertEqual(bad["rejected"], 1)

    def test_heartbeat_ingests_existing_runtime_metrics(self):
        result = record_agent_heartbeat("agent-c3", {
            "agent_id": "agent-c3",
            "instance_runtime_metrics": {
                "counters": {"reconciliations": 7},
                "queue_depth": {"runtime_events": 2},
                "durations_ms": {"reconcile": {"count": 2, "total": 30, "max": 20}},
                "observability_samples": [{"metric_name": "memory.used_ratio", "value": 0.4, "unit": "ratio"}],
            },
        }, backend=self.backend)
        self.assertGreaterEqual(result["metrics_created"], 5)
        names = {row["metric_name"] for row in self.repo.latest(agent_id="agent-c3")}
        self.assertIn("memory.used_ratio", names)
        self.assertIn("capivara.runtime.counter.reconciliations", names)


if __name__ == "__main__": unittest.main()
