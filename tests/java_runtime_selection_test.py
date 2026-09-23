#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from java_runtime import compatible_java_runtimes, select_java_executable


def load_eligibility():
    path = ROOT / "core" / "agent_eligibility.py"
    spec = importlib.util.spec_from_file_location("java_runtime_selection_agent_eligibility", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class JavaRuntimeSelectionTest(unittest.TestCase):
    def setUp(self):
        self.runtimes = [
            {"path": "/java/21/bin/java", "major": 21, "functional": True},
            {"path": "/java/25/bin/java", "major": 25, "functional": True},
        ]

    def test_exact_java_21_selects_side_by_side_runtime(self):
        selected = select_java_executable({"java": {"min": 21, "max": 21}}, runtimes=self.runtimes)
        self.assertEqual(selected, "/java/21/bin/java")

    def test_range_prefers_newest_compatible_runtime(self):
        selected = select_java_executable({"java": {"min": 17, "max": 25}}, runtimes=self.runtimes)
        self.assertEqual(selected, "/java/25/bin/java")

    def test_incompatible_range_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "No compatible Java runtime"):
            select_java_executable({"java": {"min": 17, "max": 17}}, runtimes=self.runtimes)

    def test_compatibility_filter_ignores_nonfunctional_runtime(self):
        values = compatible_java_runtimes(
            {"java": {"min": 21, "max": 21}},
            [*self.runtimes, {"path": "/bad/java", "major": 21, "functional": False}],
        )
        self.assertEqual([item["path"] for item in values], ["/java/21/bin/java"])

    def test_placement_accepts_java_21_when_default_java_is_25(self):
        from core.placement_requirements import PlacementRequirements
        from core.agent_eligibility import evaluate_agent_eligibility

        runtime = {
            "status": "active",
            "health_status": "online",
            "capabilities": {
                "java": True,
                "java_status": {"major": 25, "functional": True},
                "java_runtimes": self.runtimes,
            },
        }
        result = evaluate_agent_eligibility(
            runtime=runtime,
            port_summary={"ranges": []},
            requirements=PlacementRequirements(java_min_major=21, java_max_major=21),
        )
        self.assertTrue(result.eligible, result.reasons)

    def test_youer_26_2_requires_java_25_for_placement(self):
        from core.placement_requirements import requirements_for_instance

        requirements = requirements_for_instance(
            game_id="minecraft",
            runtime_id="minecraft.java.youer",
            version="26.2",
            catalog_root=ROOT / "catalog" / "v2",
        )
        self.assertEqual(requirements.java_min_major, 25)
        self.assertEqual(requirements.java_max_major, 25)

    def test_youer_1_21_1_keeps_java_21_requirement(self):
        from core.placement_requirements import requirements_for_instance

        requirements = requirements_for_instance(
            game_id="minecraft",
            runtime_id="minecraft.java.youer",
            version="1.21.1",
            catalog_root=ROOT / "catalog" / "v2",
        )
        self.assertEqual(requirements.java_min_major, 21)
        self.assertEqual(requirements.java_max_major, 21)

    def test_placement_falls_back_to_legacy_single_java_status(self):
        from core.placement_requirements import PlacementRequirements
        from core.agent_eligibility import evaluate_agent_eligibility

        runtime = {
            "status": "active",
            "health_status": "online",
            "capabilities": {
                "java": True,
                "java_status": {"major": 25, "functional": True},
            },
        }
        result = evaluate_agent_eligibility(
            runtime=runtime,
            port_summary={"ranges": []},
            requirements=PlacementRequirements(java_min_major=21, java_max_major=21),
        )
        self.assertFalse(result.eligible)
        self.assertIn("java_version_too_new", result.reasons)


if __name__ == "__main__":
    unittest.main()
