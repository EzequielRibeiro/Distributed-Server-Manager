#!/usr/bin/env python3

import unittest

from core.placement_diagnostics import (
    PLACEMENT_REASONS,
    placement_reasons,
    placement_status,
)


class PlacementDiagnosticsTest(unittest.TestCase):
    def test_reason_vocabulary_is_stable(self):
        self.assertEqual(
            PLACEMENT_REASONS,
            {
                "no_agents",
                "agent_pending",
                "missing_location",
                "missing_datacenter",
                "missing_region",
                "no_eligible_agents",
            },
        )

    def test_no_agents_is_primary_and_not_noisy(self):
        snapshot = {
            "agents": 0,
            "regions": 0,
            "datacenters": 0,
            "eligible_agents": 0,
        }
        self.assertEqual(placement_reasons(snapshot), ["no_agents"])
        status = placement_status(snapshot)
        self.assertFalse(status["placement_ready"])
        self.assertEqual(status["placement_reason"], "no_agents")

    def test_pending_agent_explains_incomplete_topology(self):
        snapshot = {
            "agents": 1,
            "pending_agents": 1,
            "unlocated_agents": 1,
            "regions": 0,
            "datacenters": 0,
            "eligible_agents": 0,
        }
        self.assertEqual(
            placement_reasons(snapshot),
            [
                "agent_pending",
                "missing_location",
                "missing_datacenter",
                "missing_region",
                "no_eligible_agents",
            ],
        )

    def test_ready_system_has_no_blockers(self):
        status = placement_status({"agents": 2, "eligible_agents": 1})
        self.assertTrue(status["placement_ready"])
        self.assertIsNone(status["placement_reason"])
        self.assertEqual(status["placement_reasons"], [])


if __name__ == "__main__":
    unittest.main()
