#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import game_runtime
from materializers.systemd import render_unit


class DayZSystemdShutdownTest(unittest.TestCase):
    def _build_dayz_spec(self, install: Path) -> dict:
        with patch.object(
            game_runtime.instance_runtime,
            "STATE_DIR",
            install.parent / "agent-state",
        ):
            return game_runtime.build_runtime_spec(
                {"agent_id": "agent-one"},
                {
                    "instance_id": "dayz-one",
                    "agent_id": "agent-one",
                    "game_id": "dayz",
                    "environment_id": "dayz.stable",
                    "desired_state": "stopped",
                },
                {
                    "install_path": str(install),
                    "ports": {
                        "game": {"port": 24010, "protocol": "udp"},
                        "game_aux": {"port": 24012, "protocol": "udp"},
                        "steam_query": {"port": 24013, "protocol": "udp"},
                        "battleye": {"port": 24014, "protocol": "udp"},
                    },
                },
            )

    def test_dayz_profile_declares_exit_255_as_controlled_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            spec = self._build_dayz_spec(install)

        self.assertEqual(spec["profile_version"], 14)
        self.assertEqual(spec["inaccessible_content_paths"], [str(install / "nasdara")])
        self.assertTrue(any(arg.startswith("-BEpath=") for arg in spec["arguments"]))
        self.assertEqual(spec["arguments"].count("-adminlog"), 1)
        self.assertEqual(spec["success_exit_statuses"], [255])
        unit = render_unit(spec)
        self.assertIn("\nSuccessExitStatus=255\n", unit)
        self.assertIn("\nRestart=no\n", unit)
        self.assertEqual(spec["stop_signal"], "SIGINT")
        self.assertTrue(spec["private_shared_memory"])
        self.assertIn("\nKillSignal=SIGINT\n", unit)
        self.assertIn("\nTemporaryFileSystem=/dev/shm:rw,nosuid,nodev,mode=1777\n", unit)

    def test_dayz_v6_runtime_is_migrated_to_v11_with_graceful_stop_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            current = self._build_dayz_spec(install)
            legacy = dict(current)
            legacy["profile_version"] = 6
            legacy.pop("success_exit_statuses", None)

            with patch.object(
                game_runtime.instance_runtime,
                "STATE_DIR",
                install.parent / "agent-state-migrate",
            ):
                migrated, changed = game_runtime.migrate_runtime_spec(
                    {"agent_id": "agent-one"}, legacy
                )

        self.assertTrue(changed)
        self.assertEqual(migrated["profile_version"], 14)
        self.assertEqual(migrated["profile_migrated_from_version"], 6)
        self.assertEqual(migrated["success_exit_statuses"], [255])
        self.assertEqual(migrated["stop_signal"], "SIGINT")
        self.assertIn("\nSuccessExitStatus=255\n", render_unit(migrated))
        self.assertIn("\nKillSignal=SIGINT\n", render_unit(migrated))

    def test_existing_dayz_v13_migrates_to_v14_and_masks_unused_dlc(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            current = self._build_dayz_spec(install)
            legacy = dict(current)
            legacy["profile_version"] = 13
            legacy.pop("inaccessible_content_paths", None)
            legacy["profile_context"] = dict(legacy.get("profile_context") or {}, mission="hardcore.namalsk")
            with patch.object(game_runtime.instance_runtime, "STATE_DIR", install.parent / "agent-state-migrate"):
                migrated, changed = game_runtime.migrate_runtime_spec({"agent_id": "agent-one"}, legacy)
            self.assertTrue(changed)
            self.assertEqual(migrated["profile_version"], 14)
            self.assertEqual(migrated["profile_migrated_from_version"], 13)
            self.assertEqual(migrated["inaccessible_content_paths"], [str(install / "nasdara")])
            self.assertEqual(migrated["arguments"].count("-adminlog"), 1)
            unit = render_unit(migrated)
            self.assertIn("\nInaccessiblePaths=-" + str(install / "nasdara") + "\n", unit)
            self.assertIn("-BEpath=", unit)

    def test_v13_content_activation_survives_profile_v14_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            spec = self._build_dayz_spec(install)
            legacy = dict(spec, profile_version=13)
            legacy.pop("inaccessible_content_paths", None)
            legacy.pop("content_base_arguments", None)
            legacy.pop("content_base_bind_paths", None)
            base_args = list(legacy["arguments"])
            base_binds = [dict(item) for item in legacy["bind_paths"]]
            content_mod = "-mod=@dsm-test-map;@dsm-test-workshop"
            content_key = {"source": str(install.parent / "keys"), "target": str(install / "keys")}
            legacy.update({
                "arguments": [*base_args, content_mod],
                "bind_paths": [*base_binds, content_key],
                "content_base_arguments": base_args,
                "content_base_bind_paths": base_binds,
                "content_dayz_mod_aliases": ["test-map", "test-workshop"],
                "content_dayz_keyring": content_key["source"],
                "content_dayz_key_sources": [{"id": "workshop"}],
                "content_dayz_community_missions": [{"id": "hardcore.namalsk"}],
                "dayz_content_enabled": True,
            })
            with patch.object(game_runtime.instance_runtime, "STATE_DIR", install.parent / "agent-state-migrate"):
                migrated, changed = game_runtime.migrate_runtime_spec({"agent_id": "agent-one"}, legacy)
            self.assertTrue(changed)
            self.assertEqual(migrated["profile_version"], 14)
            self.assertEqual(migrated["arguments"].count(content_mod), 1)
            self.assertEqual(migrated["arguments"].count("-adminlog"), 1)
            self.assertTrue(any(value.startswith("-BEpath=") for value in migrated["arguments"]))
            self.assertEqual(migrated["bind_paths"][-1], content_key)
            self.assertEqual(migrated["content_dayz_mod_aliases"], legacy["content_dayz_mod_aliases"])
            self.assertEqual(migrated["content_dayz_community_missions"], legacy["content_dayz_community_missions"])
            self.assertEqual(migrated["content_dayz_key_sources"], legacy["content_dayz_key_sources"])
            self.assertEqual(migrated["content_base_arguments"][-1], "-adminlog")
            self.assertEqual(len(migrated["inaccessible_content_paths"]), 1)

    def test_generic_runtime_without_declared_status_does_not_accept_255(self):
        spec = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "runtime-one",
            "user": "capivara-instance",
            "working_directory": "/srv/game",
            "executable": "/srv/game/server",
            "arguments": [],
            "environment": {},
            "secret_refs": [],
            "bind_paths": [],
            "runtime_bind_paths": [],
            "pre_start": [],
        }
        self.assertNotIn("SuccessExitStatus=255", render_unit(spec))
        self.assertIn("\nKillSignal=SIGTERM\n", render_unit(spec))
        self.assertNotIn("TemporaryFileSystem=/dev/shm", render_unit(spec))


if __name__ == "__main__":
    unittest.main()
