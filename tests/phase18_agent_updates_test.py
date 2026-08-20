#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_registration_repository import AgentRegistrationRepository
from agent_update_repository import AgentUpdateRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class Phase18AgentUpdatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db")))
        self.backend.initialize()
        registry = RegistryRepository(self.backend)
        identity = installation_profile_identity(registry, profile="controller", hostname="update-controller")
        self.controller_id = identity["controller_id"]
        registration = AgentRegistrationRepository(self.backend)
        for suffix in ("a", "b", "c"):
            registration.register(
                controller_id=self.controller_id,
                agent_id=f"agent-{suffix}",
                node_id=f"node-{suffix}",
                name=f"Agent {suffix.upper()}",
            )
        # Update rollout persistence is orthogonal to lifecycle; these rows are
        # enough to verify batching and version state.
        self.repository = AgentUpdateRepository(self.backend)
        self.repository.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_rollout_releases_batches_sequentially_after_health_verified_version(self):
        rollout = self.repository.create_rollout(
            ["agent-a", "agent-b", "agent-c"],
            desired_version="2.0.0",
            channel="stable",
            batch_size=1,
        )
        self.assertEqual(rollout["total_batches"], 3)
        self.assertIsNotNone(self.repository.command_for_agent("agent-a"))
        self.assertIsNone(self.repository.command_for_agent("agent-b"))

        self.repository.mark_updating("agent-a")
        state = self.repository.reconcile_after_heartbeat("agent-a", "2.0.0", "online")
        self.assertEqual(state["update_status"], "completed")
        completed_at = state["last_update"]
        self.assertIsNotNone(completed_at)
        self.assertIsNotNone(self.repository.command_for_agent("agent-b"))
        self.assertIsNone(self.repository.command_for_agent("agent-c"))

        # A later heartbeat must not rewrite the completion timestamp.
        repeated = self.repository.reconcile_after_heartbeat("agent-a", "2.0.0", "online")
        self.assertEqual(repeated["last_update"], completed_at)

    def test_failed_earlier_batch_blocks_later_batches(self):
        self.repository.create_rollout(
            ["agent-a", "agent-b"], desired_version="2.0.1", channel="stable", batch_size=1
        )
        self.repository.mark_updating("agent-a")
        failed = self.repository.mark_failed("agent-a", "checksum mismatch")
        self.assertEqual(failed["update_status"], "failed")
        self.assertEqual(failed["last_error"], "checksum mismatch")
        self.assertIsNone(self.repository.command_for_agent("agent-b"))

    def test_batch_size_allows_multiple_agents_but_not_next_batch(self):
        rollout = self.repository.create_rollout(
            ["agent-a", "agent-b", "agent-c"], desired_version="2.1.0", channel="beta", batch_size=2
        )
        self.assertEqual(rollout["total_batches"], 2)
        self.assertIsNotNone(self.repository.command_for_agent("agent-a"))
        self.assertIsNotNone(self.repository.command_for_agent("agent-b"))
        self.assertIsNone(self.repository.command_for_agent("agent-c"))
        self.assertEqual(self.repository.snapshot("agent-a")["update_channel"], "beta")

    def test_already_installed_target_completes_without_update_command(self):
        self.repository.report_version("agent-a", "3.0.0")
        self.repository.create_rollout(["agent-a"], desired_version="3.0.0", batch_size=1)
        state = self.repository.reconcile_after_heartbeat("agent-a", "3.0.0", "online")
        self.assertEqual(state["update_status"], "completed")
        self.assertIsNone(self.repository.command_for_agent("agent-a"))


if __name__ == "__main__":
    unittest.main()
