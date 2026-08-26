#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from adapters.systemd import SystemdAdapter


INSTANCE = {"instance_id": "example-one"}


class FakeRunner:
    def __init__(self, shows):
        self.shows = list(shows)
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        if command[:2] == ["systemctl", "show"]:
            state = self.shows.pop(0)
            return 0, (
                "LoadState=loaded\n"
                f"ActiveState={state}\n"
                f"SubState={state}\n"
            ), ""
        if command[:2] in (["systemctl", "stop"], ["systemctl", "reset-failed"]):
            return 0, "", ""
        raise AssertionError(command)


class SystemdStopNormalizationTest(unittest.TestCase):
    def test_successful_stop_clears_residual_failed_state(self):
        runner = FakeRunner(["active", "failed", "inactive"])
        result = SystemdAdapter(runner=runner).stop(INSTANCE)
        self.assertEqual(result["state"]["active_state"], "inactive")
        self.assertFalse(result["state"]["running"])
        self.assertIn(
            ["systemctl", "reset-failed", "capivara-instance-example-one.service", "--no-pager"],
            runner.commands,
        )

    def test_already_failed_stop_normalizes_without_masking_running_crashes(self):
        runner = FakeRunner(["failed", "inactive"])
        result = SystemdAdapter(runner=runner).stop(INSTANCE)
        self.assertEqual(result["state"]["active_state"], "inactive")
        self.assertTrue(result["idempotent"])
        self.assertNotIn(
            ["systemctl", "stop", "capivara-instance-example-one.service", "--no-pager"],
            runner.commands,
        )

    def test_status_does_not_clear_failed_state(self):
        runner = FakeRunner(["failed"])
        state = SystemdAdapter(runner=runner).status(INSTANCE)
        self.assertEqual(state["active_state"], "failed")
        self.assertFalse(any(command[:2] == ["systemctl", "reset-failed"] for command in runner.commands))


if __name__ == "__main__":
    unittest.main()
