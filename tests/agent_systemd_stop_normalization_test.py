#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from adapters.base import AdapterError
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
            if isinstance(state, str):
                state = {"ActiveState": state, "SubState": state}
            return 0, "LoadState=loaded\n" + "".join(
                f"{k}={v}\n" for k, v in state.items()
            ), ""
        if command[:2] in (["systemctl", "stop"], ["systemctl", "start"],
                          ["systemctl", "restart"], ["systemctl", "reset-failed"]):
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


    def test_stop_timeout_is_not_hidden_by_reset_failed(self):
        runner = FakeRunner(["active", {"ActiveState": "failed", "Result": "timeout"}])
        with self.assertRaisesRegex(AdapterError, "timed out in systemd"):
            SystemdAdapter(runner=runner).stop(INSTANCE)
        self.assertFalse(any(cmd[1] == "reset-failed" for cmd in runner.commands))

    def test_inactive_unit_with_timeout_is_not_graceful(self):
        runner = FakeRunner(["active", {"ActiveState": "inactive", "Result": "timeout"}])
        with self.assertRaisesRegex(AdapterError, "world save not confirmed"):
            SystemdAdapter(runner=runner).stop(INSTANCE)

    def test_sigkill_exit_is_not_graceful_even_if_result_changed(self):
        runner = FakeRunner(["active", {"ActiveState": "inactive", "Result": "success",
                                        "ExecMainCode": "2", "ExecMainStatus": "9"}])
        with self.assertRaisesRegex(AdapterError, "SIGKILL"):
            SystemdAdapter(runner=runner).stop(INSTANCE)

    def test_dayz_restart_does_not_start_after_timeout(self):
        runner = FakeRunner(["active", {"ActiveState": "failed", "Result": "timeout"}])
        with self.assertRaisesRegex(AdapterError, "timed out in systemd"):
            SystemdAdapter(runner=runner).restart({**INSTANCE, "game_id": "dayz"})
        actions = [cmd[1] for cmd in runner.commands]
        self.assertEqual(actions.count("stop"), 1)
        self.assertNotIn("start", actions)
        self.assertNotIn("restart", actions)
        self.assertNotIn("reset-failed", actions)

    def test_dayz_restart_stops_before_start(self):
        runner = FakeRunner(["active", "inactive", "inactive", "active"])
        with patch("adapters.systemd._SYSTEMD_START_SETTLE_SECONDS", 0.0):
            result = SystemdAdapter(runner=runner).restart({**INSTANCE, "game_id": "dayz"})
        actions = [cmd[1] for cmd in runner.commands]
        self.assertEqual(actions.count("stop"), 1)
        self.assertEqual(actions.count("start"), 1)
        self.assertNotIn("restart", actions)
        self.assertLess(actions.index("stop"), actions.index("start"))
        self.assertEqual(result["action"], "restart")
        self.assertEqual(result["state"]["active_state"], "active")

    def test_non_dayz_keeps_systemctl_restart(self):
        runner = FakeRunner(["active", "active"])
        with patch("adapters.systemd._SYSTEMD_START_SETTLE_SECONDS", 0.0):
            result = SystemdAdapter(runner=runner).restart({**INSTANCE, "game_id": "minecraft"})
        self.assertEqual(result["action"], "restart")
        self.assertIn(["systemctl", "restart", "capivara-instance-example-one.service", "--no-pager"], runner.commands)

    def test_status_exposes_process_identity_and_restart_count(self):
        def runner(command, timeout):
            if command[:2] != ["systemctl", "show"]:
                raise AssertionError(command)
            return 0, (
                "LoadState=loaded\n"
                "ActiveState=active\n"
                "SubState=running\n"
                "MainPID=4321\n"
                "NRestarts=2\n"
                "Result=success\n"
            ), ""

        state = SystemdAdapter(runner=runner).status(INSTANCE)
        self.assertEqual(state["main_pid"], 4321)
        self.assertEqual(state["restart_count"], 2)
        self.assertEqual(state["result"], "success")

    def test_status_does_not_clear_failed_state(self):
        runner = FakeRunner(["failed"])
        state = SystemdAdapter(runner=runner).status(INSTANCE)
        self.assertEqual(state["active_state"], "failed")
        self.assertFalse(any(command[:2] == ["systemctl", "reset-failed"] for command in runner.commands))


if __name__ == "__main__":
    unittest.main()
