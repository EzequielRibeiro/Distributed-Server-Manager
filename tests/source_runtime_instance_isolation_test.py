#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from profiles.registry import resolve_profile
from runtime_spec import validate_runtime_spec


class SourceRuntimeInstanceIsolationTest(unittest.TestCase):
    def ports(self, base: int = 27015) -> dict:
        return {
            "game_udp": {"port": base, "protocol": "udp"},
            "game_tcp": {"port": base, "protocol": "tcp"},
        }

    def build(self, game_id: str, instance_id: str, base: int = 27015) -> dict:
        environment_id = f"{game_id}.stable"
        executable = "srcds_run"
        args = ["-game", game_id, "-console", "+map", "gm_construct" if game_id == "garrysmod" else "c1m1_hotel"]
        instance = {
            "instance_id": instance_id,
            "agent_id": "agent-test",
            "game_id": game_id,
            "environment_id": environment_id,
            "desired_state": "stopped",
        }
        context = {
            "install_path": f"/srv/capivara/game-data/{game_id}/serverfiles",
            "instance_state_root": f"/srv/capivara/instances/{instance_id}",
            "ports": self.ports(base),
            "arguments": args,
            "catalog_runtime_policy": {
                "runtime_id": environment_id,
                "executable": executable,
                "working_directory": ".",
            },
        }
        profile = resolve_profile(instance)
        return validate_runtime_spec(
            profile.build_runtime_spec(instance, context),
            expected_agent_id="agent-test",
        )

    def test_registry_routes_source_games_away_from_catalog_native(self) -> None:
        for game_id in ("garrysmod", "left4dead2"):
            profile = resolve_profile({"game_id": game_id, "environment_id": f"{game_id}.stable"})
            self.assertEqual("SourceRuntimeProfile", profile.__class__.__name__)
        satisfactory = resolve_profile({"game_id": "satisfactory", "environment_id": "satisfactory.stable"})
        self.assertEqual("CatalogNativeRuntimeProfile", satisfactory.__class__.__name__)

    def test_garrysmod_cfg_data_and_logs_are_instance_private(self) -> None:
        spec = self.build("garrysmod", "gmod-a")
        install = Path("/srv/capivara/game-data/garrysmod/serverfiles")
        private = Path("/srv/capivara/instances/gmod-a/garrysmod")
        self.assertEqual("source", spec["profile"])
        self.assertEqual(["-port", "27015"], spec["arguments"][:2])
        self.assertEqual(
            [{"source": str(install / "garrysmod/cfg"), "target": str(private / "cfg")}],
            spec["seed_directories"],
        )
        self.assertEqual(
            [
                {"source": str(private / "cfg"), "target": str(install / "garrysmod/cfg")},
                {"source": str(private / "data"), "target": str(install / "garrysmod/data")},
                {"source": str(private / "logs"), "target": str(install / "garrysmod/logs")},
            ],
            spec["bind_paths"],
        )

    def test_left4dead2_cfg_and_logs_are_instance_private(self) -> None:
        spec = self.build("left4dead2", "l4d2-a")
        install = Path("/srv/capivara/game-data/left4dead2/serverfiles")
        private = Path("/srv/capivara/instances/l4d2-a/left4dead2")
        self.assertEqual(
            [{"source": str(install / "left4dead2/cfg"), "target": str(private / "cfg")}],
            spec["seed_directories"],
        )
        self.assertEqual(
            [
                {"source": str(private / "cfg"), "target": str(install / "left4dead2/cfg")},
                {"source": str(private / "logs"), "target": str(install / "left4dead2/logs")},
            ],
            spec["bind_paths"],
        )

    def test_two_source_instances_share_binary_but_never_mutable_paths(self) -> None:
        first = self.build("garrysmod", "gmod-a", 27015)
        second = self.build("garrysmod", "gmod-b", 27115)
        self.assertEqual(first["executable"], second["executable"])
        self.assertEqual(first["working_directory"], second["working_directory"])
        self.assertEqual(first["seed_directories"][0]["source"], second["seed_directories"][0]["source"])
        self.assertNotEqual(first["seed_directories"][0]["target"], second["seed_directories"][0]["target"])
        first_sources = {item["source"] for item in first["bind_paths"]}
        second_sources = {item["source"] for item in second["bind_paths"]}
        self.assertTrue(first_sources.isdisjoint(second_sources))
        self.assertEqual(
            {item["target"] for item in first["bind_paths"]},
            {item["target"] for item in second["bind_paths"]},
        )


if __name__ == "__main__":
    unittest.main()
