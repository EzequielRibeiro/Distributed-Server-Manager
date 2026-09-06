#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from profiles.dayz import DayZRuntimeProfile
from runtime_spec import validate_runtime_spec


class DayZInstanceMissionIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = DayZRuntimeProfile()
        self.install_path = "/srv/capivara/game-data/dayz/serverfiles"
        self.ports = {
            "game": {"port": 2302, "protocol": "udp"},
            "game_aux": {"port": 2304, "protocol": "udp"},
            "steam_query": {"port": 2305, "protocol": "udp"},
        }

    def build(self, instance_id: str) -> dict:
        instance = {
            "instance_id": instance_id,
            "agent_id": "agent-test",
            "environment_id": "dayz.stable",
            "desired_state": "stopped",
        }
        context = {
            "install_path": self.install_path,
            "ports": self.ports,
            "instance_state_root": f"/srv/capivara/instances/{instance_id}",
        }
        return validate_runtime_spec(
            self.profile.build_runtime_spec(instance, context),
            expected_agent_id="agent-test",
        )

    def test_profile_v5_keeps_shared_game_base_and_private_mission(self) -> None:
        spec = self.build("instance-a")
        self.assertEqual(5, spec["profile_version"])
        self.assertEqual(self.install_path, spec["working_directory"])
        self.assertEqual(
            f"{self.install_path}/mpmissions/dayzOffline.chernarusplus",
            spec["seed_directories"][0]["source"],
        )
        self.assertEqual(
            "/srv/capivara/instances/instance-a/mpmissions/dayzOffline.chernarusplus",
            spec["seed_directories"][0]["target"],
        )
        self.assertEqual(spec["seed_directories"][0]["target"], spec["bind_paths"][0]["source"])
        self.assertEqual(spec["seed_directories"][0]["source"], spec["bind_paths"][0]["target"])

    def test_two_instances_never_share_private_mission_path(self) -> None:
        first = self.build("instance-a")
        second = self.build("instance-b")
        self.assertEqual(first["working_directory"], second["working_directory"])
        self.assertEqual(first["executable"], second["executable"])
        self.assertEqual(first["seed_directories"][0]["source"], second["seed_directories"][0]["source"])
        self.assertNotEqual(first["seed_directories"][0]["target"], second["seed_directories"][0]["target"])
        self.assertNotEqual(first["bind_paths"][0]["source"], second["bind_paths"][0]["source"])

    def test_storage_is_part_of_private_mission_instead_of_separate_shared_bind(self) -> None:
        spec = self.build("instance-a")
        targets = [item["target"] for item in spec["bind_paths"]]
        self.assertEqual([f"{self.install_path}/mpmissions/dayzOffline.chernarusplus"], targets)
        self.assertFalse(any(target.endswith("/storage_1") for target in targets))

    def test_runtime_spec_rejects_relative_seed_directory_paths(self) -> None:
        spec = self.build("instance-a")
        spec["seed_directories"] = [{"source": "relative/source", "target": "/tmp/target"}]
        with self.assertRaises(ValueError):
            validate_runtime_spec(spec, expected_agent_id="agent-test")


if __name__ == "__main__":
    unittest.main()
