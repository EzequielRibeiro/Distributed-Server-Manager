#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "dashboard" / "workers"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SPEC = importlib.util.spec_from_file_location(
    "hybrid_agent_worker_content_test",
    ROOT / "dashboard" / "workers" / "hybrid_agent_worker.py",
)
worker = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(worker)


class _FakeClient:
    def __init__(self):
        self.commands = None

    def content_state(self):
        return [
            {
                "instance_id": "inst-1",
                "content_id": "steam-workshop:old",
                "desired_revision": 1,
                "desired_checksum": "old",
                "status": "applied",
                "security_state": "clean",
            }
        ]

    def apply_content_commands(self, config, commands):
        self.commands = (config, commands)
        return [
            {
                "instance_id": "inst-1",
                "content_id": "steam-workshop:1828439124",
                "desired_revision": 2,
                "applied_revision": 2,
                "desired_checksum": "new",
                "applied_checksum": "new",
                "status": "applied",
                "security_state": "clean",
            }
        ]


class _FakeRepository:
    instance = None

    def __init__(self, backend):
        self.backend = backend
        self.recorded = []
        self.initialized = False
        type(self).instance = self

    def initialize(self):
        self.initialized = True

    def record_agent_state(self, agent_id, reports):
        self.recorded.append((agent_id, list(reports)))
        return len(reports)

    def desired_for_agent(self, agent_id):
        return [
            {
                "instance_id": "inst-1",
                "content_id": "steam-workshop:1828439124",
                "revision": 2,
                "checksum": "new",
                "desired_state": "installed",
            }
        ]


class HybridManagedContentParityTest(unittest.TestCase):
    def test_hybrid_content_cycle_round_trips_controller_desired_state(self):
        client = _FakeClient()
        config = {"agent_id": "agent-hybrid"}

        with (
            patch.object(worker, "_hybrid_agent_config", return_value=config),
            patch.object(worker, "_content_client_module", return_value=client),
            patch.object(worker, "ContentRepository", _FakeRepository),
        ):
            result = worker.process_hybrid_content_cycle(
                object(), ROOT, "agent-hybrid"
            )

        repo = _FakeRepository.instance
        self.assertIsNotNone(repo)
        self.assertTrue(repo.initialized)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reported"], 1)
        self.assertEqual(result["commands"], 1)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(repo.recorded), 2)
        self.assertEqual(client.commands[0], config)
        self.assertEqual(
            client.commands[1][0]["content_id"],
            "steam-workshop:1828439124",
        )

    def test_hybrid_content_cycle_fails_closed_when_config_is_missing(self):
        with patch.object(worker, "_hybrid_agent_config", return_value=None):
            result = worker.process_hybrid_content_cycle(
                object(), ROOT, "agent-hybrid"
            )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "config_unavailable")
        self.assertEqual(result["commands"], 0)

    def test_hybrid_worker_configures_security_state_before_transitive_imports(self):
        source = (
            ROOT / "dashboard" / "workers" / "hybrid_agent_worker.py"
        ).read_text(encoding="utf-8")
        state_setup = source.index('os.environ.setdefault("CAPIVARA_AGENT_STATE_DIR"')
        reconciliation_import = source.index(
            "from hybrid_local_reconciliation import reconcile_local_hybrid_runtime"
        )
        self.assertLess(state_setup, reconciliation_import)
        self.assertIn('runtime" / "hybrid-agent-state"', source)

    def test_hybrid_heartbeat_refreshes_public_ipv4(self):
        source=(ROOT/"dashboard"/"workers"/"hybrid_agent_worker.py").read_text(encoding="utf-8")
        self.assertIn("process_hybrid_public_network_cycle",source)
        self.assertIn("observe_public_ipv4()",source)
        self.assertIn("sync_observed_ipv4(",source)
        self.assertIn('"public_network": public_network',source)

    def test_hybrid_heartbeat_includes_managed_content_cycle(self):
        source = (
            ROOT / "dashboard" / "workers" / "hybrid_agent_worker.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "content = process_hybrid_content_cycle(effective_backend, root, agent_id)",
            source,
        )
        self.assertIn('"content": content,', source)
        self.assertIn("content={content.get('applied', 0)}a/", source)


if __name__ == "__main__":
    unittest.main()
