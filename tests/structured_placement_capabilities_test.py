#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent_eligibility import evaluate_agent_eligibility
from core.placement_requirements import PlacementRequirements, requirements_from_runtime_definition


class StructuredPlacementRequirementsTest(unittest.TestCase):
    def test_catalog_requirements_are_carried_as_normalized_structured_fields(self):
        definition = {
            "kind": "RuntimeDefinition",
            "game": "Minecraft",
            "process": {"engine": "java"},
            "requirements": {
                "os": ["Linux", "WINDOWS"],
                "architectures": ["x86_64", "AARCH64"],
                "java": {"min": 17, "max": 21},
            },
        }
        result = requirements_from_runtime_definition(definition)
        self.assertEqual(result.game_id, "minecraft")
        self.assertEqual(result.operating_systems, frozenset({"linux", "windows"}))
        self.assertEqual(result.architectures, frozenset({"x86_64", "aarch64"}))
        self.assertEqual(result.java_min_major, 17)
        self.assertEqual(result.java_max_major, 21)
        self.assertIn("java", result.capabilities)

    def test_single_os_native_runtime_preserves_legacy_native_capability(self):
        linux = requirements_from_runtime_definition({
            "process": {"engine": "native"},
            "requirements": {"os": ["linux"]},
        })
        windows = requirements_from_runtime_definition({
            "process": {"engine": "native"},
            "requirements": {"os": ["windows"]},
        })
        self.assertIn("native-linux", linux.capabilities)
        self.assertIn("native-windows", windows.capabilities)


class StructuredAgentEligibilityTest(unittest.TestCase):
    def _runtime(self, *, os_name="linux", architecture="x86_64", java_major=21):
        return {
            "status": "active",
            "health_status": "online",
            "capabilities": {
                "java": True,
                "native-linux": os_name == "linux",
                "native-windows": os_name == "windows",
                "platform": {"os": os_name, "architecture": architecture},
                "java_status": {"functional": True, "major": java_major},
            },
        }

    def _evaluate(self, runtime, requirements):
        return evaluate_agent_eligibility(runtime=runtime, port_summary={"ranges": []}, requirements=requirements)

    def test_matching_platform_architecture_and_java_is_eligible(self):
        requirements = PlacementRequirements(
            capabilities=frozenset({"java"}),
            operating_systems=frozenset({"linux", "windows"}),
            architectures=frozenset({"x86_64", "aarch64"}),
            java_min_major=17,
            java_max_major=21,
        )
        result = self._evaluate(self._runtime(), requirements)
        self.assertTrue(result.eligible, result.reasons)
        self.assertEqual(result.reasons, ())

    def test_wrong_os_is_rejected(self):
        requirements = PlacementRequirements(operating_systems=frozenset({"windows"}))
        result = self._evaluate(self._runtime(os_name="linux"), requirements)
        self.assertFalse(result.eligible)
        self.assertIn("unsupported_platform_os", result.reasons)

    def test_missing_os_fact_fails_closed(self):
        runtime = self._runtime()
        runtime["capabilities"]["platform"].pop("os")
        requirements = PlacementRequirements(operating_systems=frozenset({"linux"}))
        result = self._evaluate(runtime, requirements)
        self.assertIn("platform_os_missing", result.reasons)

    def test_wrong_architecture_is_rejected(self):
        requirements = PlacementRequirements(architectures=frozenset({"aarch64"}))
        result = self._evaluate(self._runtime(architecture="x86_64"), requirements)
        self.assertIn("unsupported_platform_architecture", result.reasons)

    def test_missing_architecture_fact_fails_closed(self):
        runtime = self._runtime()
        runtime["capabilities"]["platform"].pop("architecture")
        requirements = PlacementRequirements(architectures=frozenset({"x86_64"}))
        result = self._evaluate(runtime, requirements)
        self.assertIn("platform_architecture_missing", result.reasons)

    def test_java_below_minimum_is_rejected(self):
        requirements = PlacementRequirements(java_min_major=21)
        result = self._evaluate(self._runtime(java_major=17), requirements)
        self.assertIn("java_version_too_old", result.reasons)

    def test_java_above_maximum_is_rejected(self):
        requirements = PlacementRequirements(java_max_major=21)
        result = self._evaluate(self._runtime(java_major=25), requirements)
        self.assertIn("java_version_too_new", result.reasons)

    def test_missing_java_version_fails_closed(self):
        runtime = self._runtime()
        runtime["capabilities"]["java_status"]["major"] = None
        requirements = PlacementRequirements(java_min_major=17)
        result = self._evaluate(runtime, requirements)
        self.assertIn("java_version_missing", result.reasons)

    def test_legacy_requirements_remain_compatible(self):
        requirements = PlacementRequirements(capabilities=frozenset({"java"}))
        runtime = {
            "status": "active",
            "health_status": "online",
            "capabilities": {"java": True},
        }
        result = self._evaluate(runtime, requirements)
        self.assertTrue(result.eligible, result.reasons)

    def test_dashboard_requires_runtime_evidence_for_structured_requirements(self):
        source = (ROOT / "dashboard/placement_eligibility.py").read_text(encoding="utf-8")
        for field in (
            "requirements.operating_systems",
            "requirements.architectures",
            "requirements.java_min_major",
            "requirements.java_max_major",
        ):
            self.assertIn(field, source)


if __name__ == "__main__":
    unittest.main()
