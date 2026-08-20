#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


from placement_readiness import (  # noqa: E402
    AGENT_STATES,
    TOPOLOGY_STATES,
    placement_ready,
    readiness_snapshot,
    topology_state,
    valid_agent_state,
)


class PlacementReadinessTest(unittest.TestCase):
    def setUp(self):
        self.controller = {"id": "controller-demo", "status": "active"}
        self.agent = {"id": "agent-demo", "status": "active"}
        self.location = {"agent_id": "agent-demo", "status": "active"}
        self.datacenter = {"id": "dc-demo", "status": "active"}
        self.region = {"id": "region-demo", "status": "active"}

    def test_official_agent_states_are_complete(self):
        self.assertEqual(
            AGENT_STATES,
            frozenset(
                {
                    "pending",
                    "pairing",
                    "active",
                    "offline",
                    "disabled",
                    "rejected",
                }
            ),
        )

    def test_official_topology_states_are_complete(self):
        self.assertEqual(
            TOPOLOGY_STATES,
            frozenset({"unconfigured", "partial", "ready"}),
        )

    def test_agent_state_validation_is_normalized(self):
        self.assertTrue(valid_agent_state(" ACTIVE "))
        self.assertFalse(valid_agent_state("unknown"))

    def test_missing_location_is_unconfigured(self):
        self.assertEqual(
            topology_state(None, self.datacenter, self.region),
            "unconfigured",
        )

    def test_incomplete_location_chain_is_partial(self):
        self.assertEqual(
            topology_state(self.location, None, self.region),
            "partial",
        )
        self.assertEqual(
            topology_state(self.location, self.datacenter, None),
            "partial",
        )

    def test_disabled_topology_member_is_partial(self):
        disabled_dc = dict(self.datacenter, status="disabled")
        self.assertEqual(
            topology_state(self.location, disabled_dc, self.region),
            "partial",
        )

    def test_complete_active_chain_is_ready(self):
        self.assertEqual(
            topology_state(self.location, self.datacenter, self.region),
            "ready",
        )

    def test_all_active_entities_are_placement_ready(self):
        self.assertTrue(
            placement_ready(
                self.controller,
                self.agent,
                self.location,
                self.datacenter,
                self.region,
            )
        )

    def test_inactive_controller_blocks_placement(self):
        controller = dict(self.controller, status="disabled")
        self.assertFalse(
            placement_ready(
                controller,
                self.agent,
                self.location,
                self.datacenter,
                self.region,
            )
        )

    def test_non_active_agent_states_block_placement(self):
        for state in AGENT_STATES - {"active"}:
            with self.subTest(state=state):
                agent = dict(self.agent, status=state)
                self.assertFalse(
                    placement_ready(
                        self.controller,
                        agent,
                        self.location,
                        self.datacenter,
                        self.region,
                    )
                )

    def test_each_topology_failure_blocks_placement(self):
        cases = (
            (None, self.datacenter, self.region),
            (dict(self.location, status="disabled"), self.datacenter, self.region),
            (self.location, None, self.region),
            (self.location, dict(self.datacenter, status="disabled"), self.region),
            (self.location, self.datacenter, None),
            (self.location, self.datacenter, dict(self.region, status="disabled")),
        )

        for location, datacenter, region in cases:
            with self.subTest(
                location=location,
                datacenter=datacenter,
                region=region,
            ):
                self.assertFalse(
                    placement_ready(
                        self.controller,
                        self.agent,
                        location,
                        datacenter,
                        region,
                    )
                )

    def test_snapshot_keeps_topology_and_placement_distinct(self):
        offline_agent = dict(self.agent, status="offline")
        snapshot = readiness_snapshot(
            self.controller,
            offline_agent,
            self.location,
            self.datacenter,
            self.region,
        )

        self.assertEqual(snapshot["topology_state"], "ready")
        self.assertFalse(snapshot["placement_ready"])


if __name__ == "__main__":
    unittest.main()
