#!/usr/bin/env python3
"""P0-E integration gate for the canonical Effective Resource Policy boundary."""
from __future__ import annotations

import unittest
from pathlib import Path

from core.effective_resource_policy import normalize_resource_policy

ROOT = Path(__file__).resolve().parents[1]


class EffectiveResourcePolicyIntegrationTest(unittest.TestCase):
    def test_catalog_units_normalize_once_and_drive_both_consumers(self):
        policy = normalize_resource_policy({
            "cpu_cores": 1.5,
            "memory_mb": 4096,
            "storage_mb": 20480,
            "swap_mb": 1024,
            "pids_limit": 512,
            "player_limit": 40,
        })
        self.assertEqual(policy.memory_bytes, 4096 * 1024 * 1024)
        self.assertEqual(policy.storage_bytes, 20480 * 1024 * 1024)
        self.assertEqual(policy.swap_bytes, 1024 * 1024 * 1024)
        self.assertEqual(policy.placement_resources(), {
            "cpu_cores": 1.5,
            "cpu_threads": 2,
            "ram_bytes": 4096 * 1024 * 1024,
            "storage_bytes": 20480 * 1024 * 1024,
        })
        self.assertEqual(policy.agent_resources(), {
            "cpu_limit_cores": 1.5,
            "memory_limit_bytes": 4096 * 1024 * 1024,
            "storage_limit_bytes": 20480 * 1024 * 1024,
            "pids_limit": 512,
            "player_limit": 40,
        })
        self.assertNotIn("swap_limit_bytes", policy.agent_resources())

    def test_canonical_limits_override_legacy_mb_aliases(self):
        policy = normalize_resource_policy({
            "memory_limit_bytes": 123456,
            "memory_mb": 8192,
            "storage_limit_bytes": 654321,
            "storage_mb": 40960,
        })
        self.assertEqual(policy.memory_bytes, 123456)
        self.assertEqual(policy.storage_bytes, 654321)

    def test_unconfigured_limits_are_omitted_from_agent_command(self):
        self.assertEqual(normalize_resource_policy({}).agent_resources(), {})
        self.assertEqual(
            normalize_resource_policy({"cpu_cores": 2}).agent_resources(),
            {"cpu_limit_cores": 2.0},
        )

    def test_customer_placement_replaces_untrusted_payload_resources(self):
        source = (ROOT / "dashboard" / "customer_instance_creation.py").read_text(encoding="utf-8")
        self.assertIn("resolve_catalog_resource_policy", source)
        self.assertIn('placement_payload=dict(payload)', source)
        self.assertIn('placement_payload["resources"]=normalize_resource_policy(effective_resource_policy).placement_resources()', source)
        self.assertNotIn('placement=legacy.resolve_instance_placement(user,payload,repository)', source)

    def test_catalog_provisioning_exposes_same_effective_policy_and_agent_limits(self):
        source = (ROOT / "dashboard" / "catalog_provisioning_resolver.py").read_text(encoding="utf-8")
        self.assertIn('config["effective_resource_policy"] = effective.as_dict()', source)
        self.assertIn('config["agent_resource_limits"] = effective.agent_resources()', source)

    def test_distributed_resource_commands_are_canonicalized_at_controller_boundary(self):
        upgrade = (ROOT / "database" / "contract_upgrade_repository.py").read_text(encoding="utf-8")
        direct = (ROOT / "database" / "instance_resource_repository.py").read_text(encoding="utf-8")
        self.assertIn("agent_resources=effective.agent_resources()", upgrade)
        self.assertIn("resources=normalize_resource_policy(dict(resources or {})).agent_resources()", direct)
        for legacy_key in ('"memory_mb"', '"storage_mb"', '"swap_mb"'):
            self.assertNotIn(f"agent_resources[{legacy_key}]", upgrade)
            self.assertNotIn(f"resources[{legacy_key}]", direct)


if __name__ == "__main__":
    unittest.main()
