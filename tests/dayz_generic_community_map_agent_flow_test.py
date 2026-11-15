#!/usr/bin/env python3
"""Temporary-filesystem end-to-end DayZ community map integration without a live game process."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for relative in ("agents/common", "agents/linux/runtime"):
    directory = str(ROOT / relative)
    if directory not in sys.path:
        sys.path.insert(0, directory)

from content_activation_runtime import project_runtime_spec
from dayz_management import apply_mission, current_mission, discover_missions


class GenericCommunityMapAgentFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm-dayz-community-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.state = self.root / "instance-state"
        self.config = self.state / "config" / "serverDZ.cfg"
        self.config.parent.mkdir(parents=True)
        self.game.mkdir()
        self.config.write_text(
            'class Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',
            encoding="utf-8",
        )
        (self.game / "mpmissions" / "dayzOffline.chernarusplus").mkdir(parents=True)
        self.map_root = self.state / "content" / "maps" / "example-map"
        self.map_root.mkdir(parents=True)
        self.base_record = {
            "instance_id": "synthetic-test-dayz",
            "agent_id": "synthetic-agent",
            "game_id": "dayz",
            "adapter": "systemd",
            "working_directory": str(self.game),
            "instance_state_root": str(self.state),
            "config_path": str(self.config),
            "arguments": ["-config=" + str(self.config)],
        }

    def _mission(self, name):
        mission = self.map_root / "Missions" / name
        (mission / "db").mkdir(parents=True)
        (mission / "init.c").write_text("void main() {}\n", encoding="utf-8")
        (mission / "db" / "types.xml").write_text("<types/>\n", encoding="utf-8")
        return mission

    def _snapshot(self, mission_path=""):
        marker = {"name": "Example Map"}
        if mission_path:
            marker["mission_path"] = mission_path
        return {
            "checksum": "fixture-only",
            "entries": [{
                "content_id": "dayz-map:example-map",
                "game_id": "dayz",
                "content_type": "map",
                "provider": "local",
                "managed_path": str(self.map_root),
                "metadata": {"community_map": marker},
            }],
        }

    def test_two_variants_remain_separate_and_preparation_does_not_switch(self):
        regular = self._mission("regular.example")
        hardcore = self._mission("hardcore.example")
        projected = project_runtime_spec(self.base_record, self._snapshot())
        self.assertEqual(projected["arguments"], self.base_record["arguments"])
        projected_names = [m["id"] for m in projected["content_dayz_community_missions"]]
        self.assertEqual(projected_names, ["hardcore.example", "regular.example"])
        by_id = {m["id"]: m for m in discover_missions(projected)["missions"]}
        for variant in ("regular.example", "hardcore.example"):
            self.assertTrue(by_id[variant]["can_activate"])
            self.assertTrue(by_id[variant]["community"])
            self.assertEqual(by_id[variant]["content_id"], "dayz-map:example-map")
            self.assertFalse(by_id[variant]["active"])
            self.assertFalse(by_id[variant]["installed"])
        self.assertEqual(current_mission(projected), "dayzOffline.chernarusplus")
        self.assertFalse((self.state / "mpmissions" / "hardcore.example").exists())
        self.assertFalse((self.state / "mpmissions" / "regular.example").exists())

        # A distinct, explicit customer action can later prepare a mission.
        # This is a pure filesystem operation on this temporary fixture.
        switched = apply_mission(projected, "hardcore.example")
        self.assertEqual(current_mission(switched), "hardcore.example")
        self.assertTrue((self.state / "mpmissions" / "hardcore.example" / "init.c").is_file())
        self.assertFalse((self.state / "mpmissions" / "regular.example").exists())
        self.assertTrue(regular.exists())
        self.assertTrue(hardcore.exists())
        self.assertEqual(switched["profile_context"]["dayz_mission"], "hardcore.example")

    def test_selecting_one_relative_path_exposes_only_requested_variant(self):
        self._mission("regular.example")
        self._mission("hardcore.example")
        projected = project_runtime_spec(self.base_record, self._snapshot("Missions/hardcore.example"))
        self.assertEqual(
            [m["id"] for m in projected["content_dayz_community_missions"]],
            ["hardcore.example"],
        )
        ids = [m["id"] for m in discover_missions(projected)["missions"]]
        self.assertIn("hardcore.example", ids)
        self.assertNotIn("regular.example", ids)

    def _windows_projector(self):
        """Load the Windows Agent's actual map projection module, not the Linux import."""
        source = ROOT / "agents" / "windows" / "runtime" / "content_activation_dayz.py"
        spec = importlib.util.spec_from_file_location("isolated_windows_dayz_projection_test", source)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_windows_and_linux_map_projection_are_equivalent(self):
        self._mission("regular.example")
        self._mission("hardcore.example")
        entries = self._snapshot()["entries"]
        linux = project_runtime_spec(self.base_record, self._snapshot())["content_dayz_community_missions"]
        windows = self._windows_projector().project_dayz_community_maps(self.base_record, entries)
        self.assertEqual(windows, linux)
        self.assertEqual(current_mission(self.base_record), "dayzOffline.chernarusplus")
        self.assertFalse((self.state / "mpmissions" / "regular.example").exists())
        self.assertFalse((self.state / "mpmissions" / "hardcore.example").exists())

    def test_windows_and_linux_specific_variant_selection_are_equivalent(self):
        self._mission("regular.example")
        self._mission("hardcore.example")
        snapshot = self._snapshot("Missions/hardcore.example")
        linux = project_runtime_spec(self.base_record, snapshot)["content_dayz_community_missions"]
        windows = self._windows_projector().project_dayz_community_maps(self.base_record, snapshot["entries"])
        self.assertEqual(windows, linux)
        self.assertEqual([m["id"] for m in windows], ["hardcore.example"])

    def test_unassigning_map_removes_prepared_community_missions(self):
        self._mission("regular.example")
        projected = project_runtime_spec(self.base_record, self._snapshot())
        self.assertIn("content_dayz_community_missions", projected)
        removed = project_runtime_spec(projected, {"checksum": "empty", "entries": []})
        self.assertNotIn("content_dayz_community_missions", removed)
        self.assertEqual(current_mission(removed), "dayzOffline.chernarusplus")

    def test_missing_requested_variant_fails_closed(self):
        self._mission("regular.example")
        with self.assertRaisesRegex(Exception, "selected DayZ community mission was not found"):
            project_runtime_spec(self.base_record, self._snapshot("Missions/hardcore.example"))


if __name__ == "__main__":
    unittest.main()
