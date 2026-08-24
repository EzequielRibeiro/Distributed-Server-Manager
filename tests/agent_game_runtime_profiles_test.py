#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import game_runtime
import instance_runtime
from materializers.systemd import render_unit
from profiles.base import GameRuntimeProfile, ProfileError, port_bindings
from profiles.registry import resolve_profile, supported_profiles
from runtime_spec import validate_runtime_spec


class ExampleSecondGameProfile(GameRuntimeProfile):
    game_ids = ("example-second-game",)

    def build_runtime_spec(self, instance, context):
        return {
            "instance_id": instance["instance_id"],
            "agent_id": instance["agent_id"],
            "game_id": "example-second-game",
            "runtime_id": instance["instance_id"],
            "adapter": "systemd",
            "working_directory": context["install_path"],
            "executable": str(Path(context["install_path"]) / "server"),
            "arguments": ["--listen", str(context["ports"]["game"])],
            "desired_state": "stopped",
        }


class GameRuntimeProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        instance_runtime.STATE_DIR = self.root / "state"
        self.config = {"agent_id": "agent-one"}
        self.instance = {
            "instance_id": "dayz-one",
            "agent_id": "agent-one",
            "game_id": "dayz",
            "environment_id": "dayz.stable",
            "desired_state": "stopped",
        }

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        self.temp.cleanup()

    def test_registry_resolves_dayz_explicitly(self):
        self.assertEqual(resolve_profile(self.instance).__class__.__name__, "DayZRuntimeProfile")
        self.assertIn("dayz", supported_profiles())
        self.assertIn("dayz.stable", supported_profiles())
        with self.assertRaises(ProfileError):
            resolve_profile({"game_id": "unknown-game"})

    def test_dayz_profile_binds_reserved_game_port_and_paths(self):
        install = self.root / "serverfiles"; install.mkdir()
        spec = game_runtime.build_runtime_spec(self.config, self.instance, {
            "install_path": str(install),
            "ports": {"game": {"port": 24010, "protocol": "udp"}, "game_aux": {"port": 24012, "protocol": "udp"}, "steam_query": {"port": 24013, "protocol": "udp"}},
        })
        self.assertEqual(spec["executable"], str(install / "DayZServer"))
        self.assertIn("-port=24010", spec["arguments"])
        self.assertIn(f"-config={install / 'serverDZ.cfg'}", spec["arguments"])
        self.assertEqual(spec["environment"]["CAPIVARA_GAME_PORT"], "24010")
        self.assertEqual(spec["environment"]["CAPIVARA_STEAM_QUERY_PORT"], "24013")
        self.assertEqual(spec["ports"]["game"], {"port": 24010, "protocol": "udp"})
        self.assertEqual(spec["ports"]["game_aux"], {"port": 24012, "protocol": "udp"})
        self.assertEqual(spec["ports"]["steam_query"], {"port": 24013, "protocol": "udp"})

    def test_profile_does_not_allocate_or_invent_required_port(self):
        install = self.root / "serverfiles"; install.mkdir()
        with self.assertRaises(ProfileError):
            game_runtime.build_runtime_spec(self.config, self.instance, {"install_path": str(install), "ports": {}})
        with self.assertRaises(ProfileError):
            port_bindings({"ports": {"game": 70000}})

    def test_profile_rejects_executable_or_config_outside_provisioned_content(self):
        install = self.root / "serverfiles"; install.mkdir()
        with self.assertRaises(ProfileError):
            game_runtime.build_runtime_spec(self.config, self.instance, {
                "install_path": str(install), "executable": "/bin/sh", "ports": {"game": 24000},
            })
        with self.assertRaises(ProfileError):
            game_runtime.build_runtime_spec(self.config, self.instance, {
                "install_path": str(install), "config_path": "/etc/passwd", "ports": {"game": 24000},
            })

    def test_agent_ownership_is_checked_before_profile_resolution(self):
        install = self.root / "serverfiles"; install.mkdir()
        foreign = {**self.instance, "agent_id": "agent-two"}
        with self.assertRaises(PermissionError):
            game_runtime.build_runtime_spec(self.config, foreign, {"install_path": str(install), "ports": {"game": 24000}})

    def test_two_profiles_converge_to_same_game_agnostic_runtime_contract(self):
        first_root = self.root / "one"; first_root.mkdir()
        dayz = game_runtime.build_runtime_spec(self.config, self.instance, {
            "install_path": str(first_root), "ports": {"game": {"port": 24000, "protocol": "udp"}, "game_aux": {"port": 24002, "protocol": "udp"}, "steam_query": {"port": 24003, "protocol": "udp"}},
        })
        second_root = self.root / "two"; second_root.mkdir()
        other_raw = ExampleSecondGameProfile().build_runtime_spec(
            {"instance_id": "second-one", "agent_id": "agent-one"},
            {"install_path": str(second_root), "ports": {"game": 25565}},
        )
        other = validate_runtime_spec(other_raw, expected_agent_id="agent-one")
        self.assertEqual(dayz["kind"], other["kind"])
        self.assertEqual(dayz["adapter"], other["adapter"])
        self.assertIn("ExecStart=", render_unit(dayz))
        self.assertIn("ExecStart=", render_unit(other))
        materializer_source = (RUNTIME / "runtime_materialization.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("dayz", materializer_source)
        self.assertNotIn("minecraft", materializer_source)


if __name__ == "__main__":
    unittest.main()
