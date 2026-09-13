#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "dashboard" / "workers"
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

import hybrid_agent_worker as worker


class _FakeWorkspaceRepository:
    contexts: dict[str, dict[str, str]] = {}
    recorded: list[tuple[str, dict]] = []

    def __init__(self, backend):
        self.backend = backend

    def initialize(self) -> None:
        return None

    def instance_context(self, instance_id: str) -> dict[str, str]:
        if instance_id not in self.contexts:
            raise KeyError(instance_id)
        return dict(self.contexts[instance_id])

    def record_telemetry(self, instance_id: str, sample: dict) -> None:
        self.recorded.append((instance_id, dict(sample)))


class HybridInstanceTelemetryTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeWorkspaceRepository.contexts = {
            "instance-owned": {"agent_id": "agent-hybrid"},
            "instance-foreign": {"agent_id": "agent-other"},
        }
        _FakeWorkspaceRepository.recorded = []
        self.observability_samples = []

    def _run(self, samples):
        telemetry = SimpleNamespace(
            collect_instance_telemetry=lambda config: samples,
        )
        def ingest(_backend, agent_id, accepted):
            self.assertEqual(agent_id, "agent-hybrid")
            self.observability_samples.extend(dict(item) for item in accepted)
            return {"accepted": len(accepted)}

        with (
            patch.object(worker, "_instance_telemetry_module", return_value=telemetry),
            patch.object(worker, "_hybrid_agent_config", return_value={"agent_id": "agent-hybrid"}),
            patch.object(worker, "InstanceWorkspaceRepository", _FakeWorkspaceRepository),
            patch.object(worker, "_ingest_hybrid_instance_observability", side_effect=ingest),
        ):
            return worker.process_hybrid_instance_telemetry_cycle(
                object(), ROOT, "agent-hybrid"
            )

    def test_persists_only_telemetry_owned_by_hybrid_agent(self) -> None:
        owned = {
            "instance_id": "instance-owned",
            "cpu_percent": 1.25,
            "memory_bytes": 4096,
            "health": "healthy",
        }
        result = self._run(
            [
                owned,
                {"instance_id": "instance-foreign", "cpu_percent": 99.0},
                {"cpu_percent": 2.0},
                "invalid",
            ]
        )

        self.assertEqual(
            result,
            {"status": "completed", "samples": 4, "accepted": 1, "rejected": 3},
        )
        self.assertEqual(_FakeWorkspaceRepository.recorded, [("instance-owned", owned)])
        self.assertEqual(self.observability_samples, [owned])

    def test_rejects_unknown_instance_without_persisting(self) -> None:
        result = self._run([{"instance_id": "missing", "health": "healthy"}])

        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(_FakeWorkspaceRepository.recorded, [])
        self.assertEqual(self.observability_samples, [])

    def test_observability_projection_contains_node_activity_metrics(self) -> None:
        captured = {}

        class FakeObservabilityRepository:
            def __init__(self, backend):
                captured["backend"] = backend

            def initialize(self):
                captured["initialized"] = True

            def ingest_agent_samples(self, agent_id, samples):
                captured["agent_id"] = agent_id
                captured["samples"] = list(samples)
                return {"accepted": len(samples)}

        backend = object()
        sample = {
            "instance_id": "instance-owned",
            "players_online": 3,
            "players_max": 16,
            "storage_used_bytes": 4096,
            "health": "healthy",
        }
        with patch.object(worker, "ObservabilityRepository", FakeObservabilityRepository):
            result = worker._ingest_hybrid_instance_observability(
                backend, "agent-hybrid", [sample]
            )

        names = {item["metric_name"] for item in captured["samples"]}
        self.assertTrue(captured["initialized"])
        self.assertIs(captured["backend"], backend)
        self.assertEqual(captured["agent_id"], "agent-hybrid")
        self.assertEqual(result["accepted"], 5)
        self.assertEqual(
            names,
            {
                "capivara.agent.players.online",
                "capivara.agent.players.capacity",
                "capivara.agent.instances.running",
                "capivara.agent.instances.total",
                "capivara.agent.instances.storage_used_bytes",
            },
        )

    def test_invalid_collector_payload_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid payload"):
            self._run({"instance_id": "instance-owned"})

    def test_missing_bootstrap_config_does_not_break_hybrid_heartbeat(self) -> None:
        with (
            patch.object(worker, "_hybrid_agent_config", return_value=None),
            patch.object(worker, "_instance_telemetry_module") as telemetry_module,
        ):
            result = worker.process_hybrid_instance_telemetry_cycle(
                object(), ROOT, "agent-hybrid"
            )

        self.assertEqual(
            result,
            {
                "status": "unavailable",
                "reason": "config_unavailable",
                "samples": 0,
                "accepted": 0,
                "rejected": 0,
            },
        )
        telemetry_module.assert_not_called()


if __name__ == "__main__":
    unittest.main()
