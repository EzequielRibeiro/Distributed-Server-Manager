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
    def test_dayz_profile_declares_exit_255_as_controlled_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "serverfiles"
            install.mkdir()
            spec = game_runtime.build_runtime_spec(
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
        self.assertEqual(spec["success_exit_statuses"], [255])
        unit = render_unit(spec)
        self.assertIn("\nSuccessExitStatus=255\n", unit)
        self.assertIn("\nRestart=no\n", unit)
        self.assertIn("\nKillSignal=SIGTERM\n", unit)

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
