#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from materializers.systemd import render_unit


class DayZSystemdShutdownTest(unittest.TestCase):
    @staticmethod
    def spec(runtime_id: str) -> dict:
        return {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": runtime_id,
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

    def test_dayz_exit_255_is_successful_controlled_shutdown(self):
        unit = render_unit(self.spec("dayz.stable"))
        self.assertIn("\nSuccessExitStatus=255\n", unit)
        self.assertIn("\nRestart=no\n", unit)
        self.assertIn("\nKillSignal=SIGTERM\n", unit)

    def test_other_games_do_not_accept_exit_255(self):
        for runtime_id in ("palworld.stable", "minecraft.java", "project-zomboid.stable"):
            with self.subTest(runtime_id=runtime_id):
                unit = render_unit(self.spec(runtime_id))
                self.assertNotIn("SuccessExitStatus=255", unit)


if __name__ == "__main__":
    unittest.main()
