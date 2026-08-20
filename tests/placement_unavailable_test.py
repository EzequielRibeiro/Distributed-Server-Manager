#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_registration_repository import AgentRegistrationRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from placement_errors import PlacementUnavailable
from placement_service import choose_agent_for_instance
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class PlacementUnavailableTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        self.backend.initialize()
        self.registry = RegistryRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_pending_agent_raises_domain_error_with_evaluated_count(self):
        controller = installation_profile_identity(
            self.registry,
            profile="controller",
            hostname="controller-one",
        )
        AgentRegistrationRepository(self.backend).register(
            controller_id=controller["controller_id"],
            agent_id="agent-pending",
            node_id="agent-pending-node",
            name="Agent Pending",
        )

        with self.assertRaises(PlacementUnavailable) as raised:
            choose_agent_for_instance(
                self.backend,
                controller_id=controller["controller_id"],
            )

        self.assertEqual(raised.exception.reason, "agent_pending")
        self.assertEqual(raised.exception.agents_evaluated, 1)
        self.assertIsNone(raised.exception.requested_region_id)

    def test_unavailable_requested_region_is_explained_internally(self):
        hybrid = installation_profile_identity(
            self.registry,
            profile="hybrid",
            hostname="hybrid-one",
        )

        with self.assertRaises(PlacementUnavailable) as raised:
            choose_agent_for_instance(
                self.backend,
                controller_id=hybrid["controller_id"],
                preferred_region_id="region-other",
                allow_cross_region=False,
            )

        self.assertEqual(
            raised.exception.reason,
            "requested_region_unavailable",
        )
        self.assertEqual(raised.exception.agents_evaluated, 1)
        self.assertEqual(
            raised.exception.requested_region_id,
            "region-other",
        )


if __name__ == "__main__":
    unittest.main()
