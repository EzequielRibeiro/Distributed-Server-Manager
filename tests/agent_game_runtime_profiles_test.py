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
import provisioning_state
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
        self.old_history = provisioning_state.HISTORY_ROOT
        instance_runtime.STATE_DIR = self.root / "state"
        provisioning_state.HISTORY_ROOT = self.root / "instance-provisioning" / "history"
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
        provisioning_state.HISTORY_ROOT = self.old_history
        self.temp.cleanup()

    def ports(self, base=24010):
        return {
            "game": {"port": base, "protocol": "udp"},
            "game_aux": {"port": base + 2, "protocol": "udp"},
            "steam_query": {"port": base + 3, "protocol": "udp"},
        }

    def test_registry_resolves_dayz_explicitly(self):
        self.assertEqual(resolve_profile(self.instance).__class__.__name__, "DayZRuntimeProfile")
        self.assertIn("dayz", supported_profiles())
        self.assertIn("dayz.stable", supported_profiles())
        with self.assertRaises(ProfileError):
            resolve_profile({"game_id": "unknown-game"})

    def test_dayz_profile_binds_reserved_game_port_and_private_paths(self):
        install = self.root / "serverfiles"; install.mkdir()
        spec = game_runtime.build_runtime_spec(self.config, self.instance, {
            "install_path": str(install), "ports": self.ports(),
        })
        private = Path("/var/lib/capivara-instances/dayz-one")
        self.assertEqual(spec["executable"], str(install / "DayZServer"))
        self.assertEqual(spec["working_directory"], str(install))
        self.assertIn("-port=24010", spec["arguments"])
        self.assertIn(f"-config={private / 'config/serverDZ.cfg'}", spec["arguments"])
        self.assertIn(f"-profiles={private / 'profiles'}", spec["arguments"])
        self.assertEqual(spec["config_path"], str(private / "config/serverDZ.cfg"))
        self.assertEqual(spec["seed_files"], [{"source": str(install / "serverDZ.cfg"), "target": str(private / "config/serverDZ.cfg")}])
        self.assertEqual(spec["bind_paths"], [{
            "source": str(private / "storage_1"),
            "target": str(install / "mpmissions/dayzOffline.chernarusplus/storage_1"),
        }])
        self.assertEqual(spec["environment"]["CAPIVARA_GAME_PORT"], "24010")
        self.assertEqual(spec["environment"]["CAPIVARA_STEAM_QUERY_PORT"], "24013")
        self.assertEqual(spec["profile_version"], 4)
        self.assertEqual(spec["ports"], self.ports())

    def test_legacy_dayz_migration_recovers_missing_ports_from_provisioning_history(self):
        install = self.root / "serverfiles"; install.mkdir()
        history = provisioning_state.HISTORY_ROOT
        history.mkdir(parents=True, exist_ok=True)
        provisioning_state.write_json(history / "legacy.request.json", {
            "provisioning_id": "legacy",
            "instance_id": "dayz-one",
            "ports": {
                "game": {"bind_address": "0.0.0.0", "port": 24010, "protocol": "udp"},
                "game_aux": {"bind_address": "0.0.0.0", "port": 24012, "protocol": "udp"},
            },
        })
        legacy = {
            "instance_id": "dayz-one",
            "agent_id": "agent-one",
            "game_id": "dayz",
            "environment_id": "dayz.stable",
            "runtime_id": "dayz.stable",
            "adapter": "systemd",
            "working_directory": str(install),
            "path": str(install),
            "executable": str(install / "DayZServer"),
            "arguments": ["-config=serverDZ.cfg"],
            "environment": {},
            "user": "capivara-instance",
            "desired_state": "running",
            "observed_state": "failed",
            "profile": "dayz",
            "profile_version": 1,
            "ports": {"game": {"port": 24010, "protocol": "udp"}},
        }
        migrated, changed = game_runtime.migrate_runtime_spec(self.config, legacy)
        self.assertTrue(changed)
        self.assertEqual(migrated["profile_version"], 4)
        self.assertEqual(migrated["profile_migrated_from_version"], 1)
        self.assertEqual(migrated["ports"]["game_aux"]["port"], 24012)
        self.assertEqual(migrated["ports"]["steam_query"]["port"], 24013)
        self.assertIn("-port=24010", migrated["arguments"])
        self.assertTrue(migrated["config_path"].endswith("/dayz-one/config/serverDZ.cfg"))
        self.assertEqual(len(migrated["bind_paths"]), 1)

    def test_dayz_v3_aliased_query_port_migrates_to_v4_catalog_topology(self):
        install = self.root / "serverfiles"; install.mkdir()
        private = "/var/lib/capivara-instances/dayz-one"
        bad_ports = {
            "game": {"port": 24010, "protocol": "udp"},
            "game_aux": {"port": 24012, "protocol": "udp"},
            "steam_query": {"port": 24012, "protocol": "udp"},
        }
        v3 = {
            "instance_id": "dayz-one",
            "agent_id": "agent-one",
            "game_id": "dayz",
            "environment_id": "dayz.stable",
            "runtime_id": "dayz.stable",
            "adapter": "systemd",
            "working_directory": str(install),
            "executable": str(install / "DayZServer"),
            "arguments": [f"-config={private}/config/serverDZ.cfg", "-port=24010", f"-profiles={private}/profiles"],
            "environment": {"CAPIVARA_STEAM_QUERY_PORT": "24012"},
            "user": "capivara-instance",
            "desired_state": "running",
            "observed_state": "running",
            "profile": "dayz",
            "profile_version": 3,
            "ports": bad_ports,
            "instance_state_root": private,
            "config_path": f"{private}/config/serverDZ.cfg",
            "profile_context": {
                "install_path": str(install),
                "working_directory": str(install),
                "executable": str(install / "DayZServer"),
                "ports": bad_ports,
                "environment": {"CAPIVARA_STEAM_QUERY_PORT": "24012"},
                "instance_state_root": private,
                "config_path": f"{private}/config/serverDZ.cfg",
            },
        }
        migrated, changed = game_runtime.migrate_runtime_spec(self.config, v3)
        self.assertTrue(changed)
        self.assertEqual(migrated["profile_version"], 4)
        self.assertEqual(migrated["profile_migrated_from_version"], 3)
        self.assertEqual(migrated["ports"]["game"]["port"], 24010)
        self.assertEqual(migrated["ports"]["game_aux"]["port"], 24012)
        self.assertEqual(migrated["ports"]["steam_query"]["port"], 24013)
        self.assertEqual(migrated["environment"]["CAPIVARA_STEAM_QUERY_PORT"], "24013")
        self.assertEqual(migrated["profile_context"]["ports"]["steam_query"]["port"], 24013)

    def test_dayz_migration_preserves_already_distinct_query_reservation(self):
        profile = resolve_profile(self.instance)
        context = {"ports": self.ports(24010)}
        upgraded = profile.upgrade_migration_context(self.instance, context, 3)
        self.assertEqual(upgraded["ports"], self.ports(24010))

    def test_dayz_profile_rejects_aliased_reserved_port_roles(self):
        install = self.root / "serverfiles"; install.mkdir()
        bad = self.ports(24010)
        bad["steam_query"] = dict(bad["game_aux"])
        with self.assertRaisesRegex(ProfileError, "distinct ports"):
            game_runtime.build_runtime_spec(self.config, self.instance, {
                "install_path": str(install), "ports": bad,
            })

    def test_two_dayz_instances_never_share_config_profiles_or_persistence(self):
        install = self.root / "serverfiles"; install.mkdir()
        first = game_runtime.build_runtime_spec(self.config, self.instance, {"install_path": str(install), "ports": self.ports(24010)})
        second_instance = {**self.instance, "instance_id": "dayz-two"}
        second = game_runtime.build_runtime_spec(self.config, second_instance, {"install_path": str(install), "ports": self.ports(24110)})
        self.assertNotEqual(first["config_path"], second["config_path"])
        self.assertNotEqual(first["bind_paths"][0]["source"], second["bind_paths"][0]["source"])
        self.assertEqual(first["bind_paths"][0]["target"], second["bind_paths"][0]["target"])
        self.assertIn("-port=24010", first["arguments"])
        self.assertIn("-port=24110", second["arguments"])

    def test_profile_does_not_allocate_or_invent_required_port(self):
        install = self.root / "serverfiles"; install.mkdir()
        with self.assertRaises(ProfileError):
            game_runtime.build_runtime_spec(self.config, self.instance, {"install_path": str(install), "ports": {}})
        with self.assertRaises(ProfileError):
            port_bindings({"ports": {"game": 70000}})

    def test_profile_rejects_executable_or_config_outside_allowed_roots(self):
        install = self.root / "serverfiles"; install.mkdir()
        with self.assertRaises(ProfileError):
            game_runtime.build_runtime_spec(self.config, self.instance, {
                "install_path": str(install), "executable": "/bin/sh", "ports": self.ports(24000),
            })
        with self.assertRaises(ProfileError):
            game_runtime.build_runtime_spec(self.config, self.instance, {
                "install_path": str(install), "config_path": "/etc/passwd", "ports": self.ports(24000),
            })

    def test_agent_ownership_is_checked_before_profile_resolution(self):
        install = self.root / "serverfiles"; install.mkdir()
        foreign = {**self.instance, "agent_id": "agent-two"}
        with self.assertRaises(PermissionError):
            game_runtime.build_runtime_spec(self.config, foreign, {"install_path": str(install), "ports": self.ports(24000)})

    def test_two_profiles_converge_to_same_game_agnostic_runtime_contract(self):
        first_root = self.root / "one"; first_root.mkdir()
        dayz = game_runtime.build_runtime_spec(self.config, self.instance, {
            "install_path": str(first_root), "ports": self.ports(24000),
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
