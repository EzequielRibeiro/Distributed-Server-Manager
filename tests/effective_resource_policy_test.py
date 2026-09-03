#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.effective_resource_policy import normalize_resource_policy


class EffectiveResourcePolicyTest(unittest.TestCase):
    def test_catalog_profile_units_are_normalized_to_canonical_bytes(self):
        policy = normalize_resource_policy({
            "cpu_cores": 2.5,
            "memory_mb": 4096,
            "storage_mb": 10240,
            "swap_mb": 512,
            "pids_limit": 768,
            "player_limit": 32,
        })
        self.assertEqual(policy.cpu_cores, 2.5)
        self.assertEqual(policy.memory_bytes, 4096 * 1024 * 1024)
        self.assertEqual(policy.storage_bytes, 10240 * 1024 * 1024)
        self.assertEqual(policy.swap_bytes, 512 * 1024 * 1024)
        self.assertEqual(policy.pids_limit, 768)
        self.assertEqual(policy.player_limit, 32)

    def test_canonical_fields_win_over_compatibility_aliases(self):
        policy = normalize_resource_policy({
            "cpu_limit_cores": 3.25,
            "cpu_cores": 1,
            "memory_limit_bytes": 123456,
            "memory_mb": 4096,
            "storage_limit_bytes": 654321,
            "storage_mb": 9999,
        })
        self.assertEqual(policy.cpu_cores, 3.25)
        self.assertEqual(policy.memory_bytes, 123456)
        self.assertEqual(policy.storage_bytes, 654321)

    def test_fractional_cpu_is_rounded_up_only_for_placement_threads(self):
        policy = normalize_resource_policy({"cpu_cores": 2.25})
        self.assertEqual(policy.placement_resources(), {"cpu_cores": 2.25, "cpu_threads": 3})
        self.assertEqual(policy.agent_resources(), {"cpu_limit_cores": 2.25})

    def test_agent_resources_omit_unconfigured_zero_limits(self):
        policy = normalize_resource_policy({"memory_mb": 2048})
        self.assertEqual(policy.agent_resources(), {"memory_limit_bytes": 2048 * 1024 * 1024})
        self.assertNotIn("cpu_limit_cores", policy.agent_resources())
        self.assertNotIn("pids_limit", policy.agent_resources())
        self.assertNotIn("player_limit", policy.agent_resources())

    def test_swap_is_canonical_but_not_claimed_as_agent_enforced(self):
        policy = normalize_resource_policy({"swap_mb": 512})
        self.assertEqual(policy.swap_bytes, 512 * 1024 * 1024)
        self.assertNotIn("swap_limit_bytes", policy.agent_resources())

    def test_invalid_and_negative_values_do_not_create_limits(self):
        policy = normalize_resource_policy({
            "cpu_cores": "invalid",
            "memory_mb": -1,
            "storage_bytes": -5,
            "pids_limit": -3,
        })
        self.assertEqual(policy.placement_resources(), {})
        self.assertEqual(policy.agent_resources(), {})


if __name__ == "__main__":
    unittest.main()
