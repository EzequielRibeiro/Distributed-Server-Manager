#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import dayz_operation_client


class DayZMapSwitchStabilizationTest(unittest.TestCase):
    def test_rejects_process_restart_even_if_runtime_is_running_again(self):
        views = [
            {
                "observed_state": "running",
                "adapter_state": {
                    "main_pid": 100,
                    "restart_count": 0,
                    "result": "success",
                },
            },
            {
                "observed_state": "running",
                "adapter_state": {
                    "main_pid": 101,
                    "restart_count": 0,
                    "result": "success",
                },
            },
        ]
        with (
            patch.dict(os.environ, {"CAPIVARA_DAYZ_SWITCH_STABILIZE_SECONDS": "1"}),
            patch.object(dayz_operation_client, "status", side_effect=views),
            patch.object(dayz_operation_client.time, "monotonic", side_effect=[0.0, 0.0, 0.5, 0.6]),
            patch.object(dayz_operation_client.time, "sleep", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "restarted during map-switch stabilization"):
                dayz_operation_client._stabilize({}, "dayz-1")

    def test_rejects_systemd_oom_result_before_reporting_success(self):
        view = {
            "observed_state": "running",
            "adapter_state": {
                "main_pid": 100,
                "restart_count": 0,
                "result": "oom-kill",
            },
        }
        with (
            patch.dict(os.environ, {"CAPIVARA_DAYZ_SWITCH_STABILIZE_SECONDS": "1"}),
            patch.object(dayz_operation_client, "status", return_value=view),
            patch.object(dayz_operation_client.time, "monotonic", side_effect=[0.0, 0.0]),
        ):
            with self.assertRaisesRegex(RuntimeError, "systemd result oom-kill"):
                dayz_operation_client._stabilize({}, "dayz-1")

    def test_runtime_identity_reads_systemd_process_fields(self):
        pid, restarts, result = dayz_operation_client._runtime_identity({
            "adapter_state": {
                "main_pid": "4321",
                "restart_count": "2",
                "result": "success",
            }
        })
        self.assertEqual(pid, 4321)
        self.assertEqual(restarts, 2)
        self.assertEqual(result, "success")


if __name__ == "__main__":
    unittest.main()
