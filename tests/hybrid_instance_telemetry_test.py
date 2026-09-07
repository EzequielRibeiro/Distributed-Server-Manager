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

    def _run(self, samples):
        telemetry = SimpleNamespace(
            collect_instance_telemetry=lambda config: samples,
        )
        with (
            patch.object(worker, "_instance_telemetry_module", return_value=telemetry),
            patch.object(worker, "_hybrid_agent_config", return_value={"agent_id": "agent-hybrid"}),
            patch.object(worker, "InstanceWorkspaceRepository", _FakeWorkspaceRepository),
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

    def test_rejects_unknown_instance_without_persisting(self) -> None:
        result = self._run([{"instance_id": "missing", "health": "healthy"}])

        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(_FakeWorkspaceRepository.recorded, [])

    def test_invalid_collector_payload_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid payload"):
            self._run({"instance_id": "instance-owned"})


if __name__ == "__main__":
    unittest.main()
