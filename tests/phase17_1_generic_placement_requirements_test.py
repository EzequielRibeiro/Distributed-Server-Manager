#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.placement_requirements import (
    load_runtime_definition,
    requirements_for_instance,
    requirements_from_runtime_definition,
)


class GenericPlacementRequirementsTest(unittest.TestCase):
    def test_arbitrary_future_game_requires_no_core_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary)
            game_dir = catalog / "future-game"
            game_dir.mkdir(parents=True)
            definition = {
                "schema_version": 2,
                "kind": "RuntimeDefinition",
                "id": "future-game.stable",
                "game": "future-game",
                "process": {"engine": "docker", "executable": "server"},
                "requirements": {"os": ["linux"], "architectures": ["x86_64"]},
                "artifact": {"provider": "steam", "auth": "anonymous"},
                "network": {
                    "allocation": "block",
                    "block_size": 4,
                    "ports": [
                        {"name": "game", "protocol": "udp", "offset": 0},
                        {"name": "query", "protocol": "udp", "offset": 1},
                    ],
                },
                "placement": {
                    "capabilities": ["gpu-runtime"],
                    "resources": {"cpu_threads": 4, "ram_bytes": 8589934592},
                },
            }
            path = game_dir / "stable.json"
            path.write_text(json.dumps(definition), encoding="utf-8")

            loaded = load_runtime_definition("future-game.stable", catalog_root=catalog)
            self.assertEqual(loaded["game"], "future-game")
            requirements = requirements_for_instance(
                game_id="future-game",
                runtime_id="future-game.stable",
                catalog_root=catalog,
            )
            self.assertEqual(
                requirements.capabilities,
                frozenset({"docker", "steamcmd", "gpu-runtime"}),
            )
            self.assertEqual(requirements.min_cpu_threads, 4)
            self.assertEqual(requirements.min_ram_bytes, 8589934592)
            self.assertEqual(len(requirements.ports), 1)
            self.assertEqual(requirements.ports[0].protocol, "udp")
            self.assertEqual(requirements.ports[0].count, 4)
            self.assertTrue(requirements.ports[0].contiguous)

    def test_explicit_placement_ports_override_network_inference(self):
        requirements = requirements_from_runtime_definition({
            "kind": "RuntimeDefinition",
            "id": "custom",
            "game": "custom",
            "network": {
                "allocation": "block",
                "block_size": 20,
                "ports": [{"name": "game", "protocol": "udp", "offset": 0}],
            },
            "placement": {
                "ports": [
                    {"protocol": "tcp", "count": 3, "contiguous": False}
                ]
            },
        })
        self.assertEqual(len(requirements.ports), 1)
        self.assertEqual(requirements.ports[0].protocol, "tcp")
        self.assertEqual(requirements.ports[0].count, 3)
        self.assertFalse(requirements.ports[0].contiguous)

    def test_unknown_runtime_does_not_invent_game_requirements(self):
        requirements = requirements_for_instance(
            game_id="unseen-game",
            runtime_id="unseen-game.experimental",
        )
        self.assertEqual(requirements.game_id, "unseen-game")
        self.assertFalse(requirements.capabilities)
        self.assertFalse(requirements.ports)


if __name__ == "__main__":
    unittest.main()
