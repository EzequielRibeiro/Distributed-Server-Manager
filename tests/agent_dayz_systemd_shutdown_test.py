#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import game_runtime
from materializers.systemd import render_unit


class DayZSystemdShutdownTest(unittest.TestCase):
    def _build_dayz_spec(self, install: Path) -> dict:
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
                },
            },
        )

    def test_dayz_profile_declares_exit_255_as_controlled_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            spec = self._build_dayz_spec(install)

        self.assertEqual(spec["profile_version"], 9)
        self.assertEqual(spec["success_exit_statuses"], [255])
        unit = render_unit(spec)
        self.assertIn("\nSuccessExitStatus=255\n", unit)
        self.assertIn("\nRestart=no\n", unit)
        self.assertIn("\nKillSignal=SIGTERM\n", unit)

    def test_dayz_v6_runtime_is_migrated_to_v9_with_success_exit_status(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            current = self._build_dayz_spec(install)
            legacy = dict(current)
            legacy["profile_version"] = 6
            legacy.pop("success_exit_statuses", None)

            migrated, changed = game_runtime.migrate_runtime_spec(
                {"agent_id": "agent-one"}, legacy
            )

        self.assertTrue(changed)
        self.assertEqual(migrated["profile_version"], 9)
        self.assertEqual(migrated["profile_migrated_from_version"], 6)
        self.assertEqual(migrated["success_exit_statuses"], [255])
        self.assertIn("\nSuccessExitStatus=255\n", render_unit(migrated))

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


if __name__ == "__main__":
    unittest.main()
