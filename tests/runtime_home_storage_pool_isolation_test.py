#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
MATERIALIZERS = RUNTIME / "materializers"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(MATERIALIZERS))

from profiles.catalog_native import CatalogNativeRuntimeProfile
from runtime_spec import validate_runtime_spec
from materializers.systemd import render_unit


class RuntimeHomeStoragePoolIsolationTest(unittest.TestCase):
    def _satisfactory_spec(self, instance_id: str, state_root: str) -> dict:
        install = "/srv/capivara/game-data/satisfactory/serverfiles"
        instance = {
            "instance_id": instance_id,
            "agent_id": "agent-1",
            "game_id": "satisfactory",
            "environment_id": "satisfactory.stable",
        }
        context = {
            "install_path": install,
            "instance_state_root": state_root,
            "ports": [
                {"role": "game", "port": 7777 if instance_id == "sat-a" else 7778, "protocol": "udp"},
            ],
            "catalog_runtime_policy": {
                "runtime_id": "satisfactory.stable",
                "executable": "FactoryServer.sh",
                "working_directory": ".",
            },
        }
        return validate_runtime_spec(
            CatalogNativeRuntimeProfile().build_runtime_spec(instance, context),
            expected_agent_id="agent-1",
        )

    def test_two_instances_share_game_content_but_not_home(self):
        first = self._satisfactory_spec("sat-a", "/mnt/pool-a/instances/sat-a")
        second = self._satisfactory_spec("sat-b", "/mnt/pool-b/instances/sat-b")

        self.assertEqual(first["working_directory"], second["working_directory"])
        self.assertEqual(first["executable"], second["executable"])
        self.assertNotEqual(first["instance_state_root"], second["instance_state_root"])

        first_unit = render_unit(first)
        second_unit = render_unit(second)

        self.assertIn(
            "BindPaths=/mnt/pool-a/instances/sat-a:/var/lib/capivara-agent/runtime-home",
            first_unit,
        )
        self.assertIn(
            "BindPaths=/mnt/pool-b/instances/sat-b:/var/lib/capivara-agent/runtime-home",
            second_unit,
        )
        self.assertNotIn("/var/lib/capivara-instances/sat-a:/var/lib/capivara-agent/runtime-home", first_unit)
        self.assertNotIn("/var/lib/capivara-instances/sat-b:/var/lib/capivara-agent/runtime-home", second_unit)
        self.assertIn('Environment="HOME=/var/lib/capivara-agent/runtime-home"', first_unit)
        self.assertIn('Environment="XDG_CONFIG_HOME=/var/lib/capivara-agent/runtime-home/.config"', first_unit)

    def test_default_storage_root_keeps_systemd_state_directory(self):
        spec = self._satisfactory_spec("sat-a", "/var/lib/capivara-instances/sat-a")
        unit = render_unit(spec)
        self.assertIn("StateDirectory=capivara-instances/sat-a", unit)
        self.assertIn(
            "BindPaths=/var/lib/capivara-instances/sat-a:/var/lib/capivara-agent/runtime-home",
            unit,
        )

    def test_custom_storage_root_does_not_create_shadow_default_state(self):
        spec = self._satisfactory_spec("sat-a", "/mnt/pool-a/instances/sat-a")
        unit = render_unit(spec)
        self.assertNotIn("StateDirectory=capivara-instances/sat-a", unit)


if __name__ == "__main__":
    unittest.main()
