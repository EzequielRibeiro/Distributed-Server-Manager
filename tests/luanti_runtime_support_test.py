#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from game_data_installer import validate_installer
from profiles.luanti import LuantiRuntimeProfile


class LuantiRuntimeSupportTest(unittest.TestCase):
    def test_cmake_installer_is_closed_and_structured(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            source = target / "luanti-5.17.0"
            source.mkdir()
            (source / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.5)\n", encoding="utf-8")
            selection = {
                "installer": {
                    "type": "cmake_source",
                    "args": [],
                    "source_dir": "luanti-5.17.0",
                    "build_dir": ".capivara-build",
                    "definitions": {
                        "BUILD_SERVER": "TRUE",
                        "BUILD_CLIENT": "FALSE",
                        "RUN_IN_PLACE": "TRUE",
                        "CMAKE_BUILD_TYPE": "Release",
                    },
                    "expected_outputs": ["luanti-5.17.0/bin/luantiserver"],
                }
            }
            with patch("game_data_installer.shutil.which", return_value="/usr/bin/cmake"):
                commands, _, _, _ = validate_installer(selection, target)
            self.assertEqual(commands[0][0], "/usr/bin/cmake")
            self.assertIn("-DBUILD_SERVER=TRUE", commands[0])
            self.assertIn("-DBUILD_CLIENT=FALSE", commands[0])
            self.assertEqual(commands[1][0:2], ["/usr/bin/cmake", "--build"])

    def test_cmake_installer_rejects_untrusted_definition(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            source = target / "src"
            source.mkdir()
            (source / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.5)\n", encoding="utf-8")
            selection = {"installer": {
                "type": "cmake_source", "args": [], "source_dir": "src",
                "definitions": {"CMAKE_C_COMPILER": "/tmp/evil"},
            }}
            with patch("game_data_installer.shutil.which", return_value="/usr/bin/cmake"):
                with self.assertRaises(ValueError):
                    validate_installer(selection, target)

    def test_runtime_profile_keeps_world_private(self):
        instance = {
            "instance_id": "luanti-1",
            "agent_id": "agent-1",
            "game_id": "luanti",
            "environment_id": "luanti.stable",
        }
        context = {
            "install_path": "/opt/dsm/game-data/luanti/serverfiles",
            "instance_state_root": "/var/lib/capivara-instances/luanti-1",
            "catalog_runtime_policy": {
                "runtime_id": "luanti.stable",
                "executable": "luanti-5.17.0/bin/luantiserver",
            },
            "ports": {"game": {"port": 30000, "protocol": "udp"}},
        }
        spec = LuantiRuntimeProfile().build_runtime_spec(instance, context)
        self.assertEqual(spec["profile"], "luanti")
        self.assertIn("/var/lib/capivara-instances/luanti-1/world", spec["arguments"])
        self.assertIn("30000", spec["arguments"])
        self.assertTrue(spec["executable"].endswith("/luanti-5.17.0/bin/luantiserver"))

    def test_catalog_has_zero_deferred_runtimes(self):
        matrix = json.loads((ROOT / "catalog" / "v2" / "support-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(matrix["deferred_runtimes"], [])
        published = {item["id"] for item in matrix["published_runtimes"]}
        self.assertIn("luanti.stable", published)
        self.assertTrue((ROOT / "catalog" / "v2" / "games" / "luanti" / "runtimes" / "stable.json").is_file())
        self.assertFalse((ROOT / "catalog" / "v2" / "games" / "luanti" / "deferred" / "stable.json").exists())


if __name__ == "__main__":
    unittest.main()
