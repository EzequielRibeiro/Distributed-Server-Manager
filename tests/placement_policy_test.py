#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from core.placement.placement_policy import (
    PlacementCandidate,
    PlacementRequest,
    choose_candidate,
)


class PlacementPolicyTest(unittest.TestCase):
    def test_preferred_region_is_respected(self):
        request = PlacementRequest(
            controller_id="controller-demo",
            preferred_region_id="br-sao",
            allow_cross_region=False,
        )

        result = choose_candidate(
            request,
            [
                PlacementCandidate(
                    agent_id="china",
                    node_id="node-cn",
                    region_id="cn-sha",
                    datacenter_id="dc-cn",
                    instance_count=0,
                ),
                PlacementCandidate(
                    agent_id="sao-paulo",
                    node_id="node-br",
                    region_id="br-sao",
                    datacenter_id="dc-br",
                    instance_count=20,
                ),
            ],
        )

        self.assertEqual(
            result.candidate.agent_id,
            "sao-paulo",
        )

    def test_latency_breaks_same_region_choice(self):
        request = PlacementRequest(
            controller_id="controller-demo",
            preferred_region_id="br-sao",
            latency_ms={
                "agent-a": 42.0,
                "agent-b": 11.0,
            },
        )

        result = choose_candidate(
            request,
            [
                PlacementCandidate(
                    agent_id="agent-a",
                    node_id="node-a",
                    region_id="br-sao",
                    datacenter_id="dc-a",
                ),
                PlacementCandidate(
                    agent_id="agent-b",
                    node_id="node-b",
                    region_id="br-sao",
                    datacenter_id="dc-b",
                ),
            ],
        )

        self.assertEqual(
            result.candidate.agent_id,
            "agent-b",
        )


if __name__ == "__main__":
    unittest.main()
