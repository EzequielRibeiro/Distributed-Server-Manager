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

    def test_activation_order_is_reported_in_projected_snapshot_order(self):
        snapshot = {
            "entries": [
                {"content_id": "cf", "game_id": "dayz", "package_id": "221100:1559212036", "activation_order": 10},
                {"content_id": "vpp", "game_id": "dayz", "package_id": "221100:1828439124", "activation_order": 20},
                {"content_id": "codelock", "game_id": "dayz", "package_id": "221100:1646187754", "activation_order": 30},
            ]
        }
        self.assertEqual(
            [item["content_id"] for item in dayz_operation_client._activation_order(snapshot)],
            ["cf", "vpp", "codelock"],
        )

    def test_hybrid_rollback_repairs_file_access_through_privileged_helper(self):
        completed = type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        with (
            patch.dict(
                os.environ,
                {"CAPIVARA_MATERIALIZER_UNIT_TEMPLATE": "dsm-hybrid-agent-materialize@{instance_id}.service"},
                clear=False,
            ),
            patch.object(dayz_operation_client.subprocess, "run", return_value=completed) as run,
        ):
            unit = dayz_operation_client._repair_hybrid_file_access("dayz-1")
        self.assertEqual(unit, "dsm-hybrid-agent-files-access@dayz-1.service")
        run.assert_called_once_with(
            ["systemctl", "start", "dsm-hybrid-agent-files-access@dayz-1.service", "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_non_hybrid_rollback_does_not_require_file_access_helper(self):
        with (
            patch.dict(os.environ, {"CAPIVARA_MATERIALIZER_UNIT_TEMPLATE": "capivara-agent-materialize@{instance_id}.service"}, clear=False),
            patch.object(dayz_operation_client.subprocess, "run") as run,
        ):
            unit = dayz_operation_client._repair_hybrid_file_access("dayz-1")
        self.assertIsNone(unit)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
