#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.placement import PlacementCandidate, PlacementRequest, choose_candidate


def candidate(agent_id: str, region_id: str, *, load: int = 0, latitude=None, longitude=None):
    return PlacementCandidate(
        agent_id=agent_id,
        node_id=f"node-{agent_id}",
        region_id=region_id,
        datacenter_id=f"dc-{region_id}",
        instance_count=load,
        latitude=latitude,
        longitude=longitude,
    )


class GeographicPlacementLatencyP6Test(unittest.TestCase):
    def test_public_region_latency_can_rank_without_agent_topology(self):
        decision = choose_candidate(
            PlacementRequest(
                controller_id="controller-a",
                region_latency_ms={"br-sudeste": 48, "us-east": 115},
                allow_cross_region=True,
            ),
            [candidate("agent-z", "br-sudeste", load=4), candidate("agent-a", "us-east")],
        )
        self.assertEqual(decision.candidate.region_id, "br-sudeste")
        self.assertEqual(decision.latency_ms, 48.0)
        self.assertEqual(decision.latency_source, "region-measured")
        self.assertIn("latency-source=region-measured", decision.reason)

    def test_internal_agent_measurement_has_priority_over_region_measurement(self):
        decision = choose_candidate(
            PlacementRequest(
                controller_id="controller-a",
                latency_ms={"agent-a": 30},
                region_latency_ms={"br-sudeste": 80},
            ),
            [candidate("agent-a", "br-sudeste")],
        )
        self.assertEqual(decision.latency_ms, 30.0)
        self.assertEqual(decision.latency_source, "agent-measured")

    def test_explicit_region_remains_hard_constraint_before_latency(self):
        decision = choose_candidate(
            PlacementRequest(
                controller_id="controller-a",
                preferred_region_id="br-sudeste",
                region_latency_ms={"br-sudeste": 200, "us-east": 5},
                allow_cross_region=False,
            ),
            [candidate("agent-br", "br-sudeste"), candidate("agent-us", "us-east")],
        )
        self.assertEqual(decision.candidate.agent_id, "agent-br")

    def test_geographic_distance_is_deterministic_fallback(self):
        decision = choose_candidate(
            PlacementRequest(
                controller_id="controller-a",
                client_latitude=-23.55,
                client_longitude=-46.63,
                allow_cross_region=True,
            ),
            [
                candidate("agent-us", "us-east", latitude=25.76, longitude=-80.19),
                candidate("agent-br", "br-sudeste", latitude=-23.56, longitude=-46.64),
            ],
        )
        self.assertEqual(decision.candidate.agent_id, "agent-br")
        self.assertEqual(decision.latency_source, "geographic-estimate")
        self.assertIsNotNone(decision.distance_km)

    def test_invalid_latency_is_ignored_and_falls_back(self):
        decision = choose_candidate(
            PlacementRequest(
                controller_id="controller-a",
                region_latency_ms={"br-sudeste": -1},
                client_latitude=-23.55,
                client_longitude=-46.63,
            ),
            [candidate("agent-br", "br-sudeste", latitude=-23.56, longitude=-46.64)],
        )
        self.assertIsNone(decision.latency_ms)
        self.assertEqual(decision.latency_source, "geographic-estimate")

    def test_ties_are_resolved_by_agent_id(self):
        decision = choose_candidate(
            PlacementRequest(controller_id="controller-a"),
            [candidate("agent-z", "br-sudeste"), candidate("agent-a", "br-sudeste")],
        )
        self.assertEqual(decision.candidate.agent_id, "agent-a")
        self.assertEqual(decision.latency_source, "unavailable")


if __name__ == "__main__":
    unittest.main()
